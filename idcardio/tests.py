"""ID cards (backend spec §10.1 golden vectors C1-C15, §10.2 properties) and
the API: permissions, tenancy, versioning, print jobs and verification.

The clock is frozen on 2026-10-15."""

import io
import shutil
import tempfile
from datetime import date

from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from PIL import Image

from companyio.models import CompanyDesignation
from employeeio.test_support import ApiMixin, FrozenClockMixin, make_company, make_company_admin, make_employee, make_user

from .models import Card, CardAudit, CardField, CardTemplate, OutputProfile, PrintJob
from .services import context as C
from .services import ops
from .services.engine import ApproxMeasurer, effective_dpi, preflight_side, pt_to_mm, px_at
from .services.metrics import FontMeasurer, prime
from .services.seed import binding, el, ensure_setup, frame, literal, style

TODAY = date(2026, 10, 15)
API = "/api/v1/we/idcards"
MEDIA = tempfile.mkdtemp(prefix="idcards-test-")


def png(w=300, h=400, colour=(180, 140, 120)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="JPEG")
    return SimpleUploadedFile("photo.jpg", buf.getvalue(), content_type="image/jpeg")


def give(user, company, *codenames):
    from adminio.models import CompanyRole
    from companyio.models import CompanyUser

    role, _ = CompanyRole.objects.get_or_create(company=company, name="Cards " + "-".join(codenames))
    role.permission.add(*Permission.objects.filter(content_type__app_label="idcardio", codename__in=codenames))
    CompanyUser.objects.get(user=user, company=company).roles.add(role)


AB = {"width": 85.6, "height": 54.0, "bleed": 2.0, "safe": 3.0, "radius": 3.18}


def side(*elements, background=None):
    return {"kind": "front", "background": background or {"type": "solid", "color": "#FFFFFF"},
            "elements": list(elements)}


def ctx(**employee):
    return {"employee": {"fullName": "Md. Karim Uddin", **employee}, "company": {"name": "Rahman Garments"},
            "card": C.card_ctx(None), "custom": {}}


@override_settings(MEDIA_ROOT=MEDIA)
class Base(FrozenClockMixin, TestCase):
    frozen_on = TODAY

    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Rahman Garments")
        cls.sewing = CompanyDesignation.objects.create(company=cls.company, title="Sewing Operator")
        cls.emp = make_employee(cls.company, "EMP-0001", "Md. Rafiqul Islam", name_bn="মোঃ রফিকুল ইসলাম",
                                designation=cls.sewing, status="ACTIVE", blood="B+", mobile="01711000000",
                                nid="1990123456789")
        ensure_setup(cls.company)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        cache.clear()

    def standard(self):
        return ops.published(self.company, "standard")

    def with_photo(self, employee=None, w=600, h=750):
        return ops.upload_asset(self.company, employee or self.emp, png(w, h))

    def issue(self, employee=None, **kw):
        employee = employee or self.emp
        if not C.current_photos([employee]):
            self.with_photo(employee)
        return ops.issue_card(self.company, employee, **kw)[0]


# ----------------------------------------------------------- golden vectors


class GoldenTests(Base):
    def test_c1_cr80_at_300_dpi(self):
        self.assertAlmostEqual(px_at(85.6, 300), 1011, delta=1)
        self.assertAlmostEqual(px_at(54.0, 300), 638, delta=1)

    def test_c2_10pt_is_3_528mm(self):
        self.assertEqual(round(pt_to_mm(10), 3), 3.528)

    def photo_side(self, width_mm):
        return side(el("p", "Photo", "photo", frame(10, 5, width_mm, width_mm * 4 / 3), path="employee.photo",
                       fit="cover", minDpi=300))

    def test_c3_300px_at_25mm_is_305_dpi_no_warning(self):
        self.assertEqual(effective_dpi(300, 25), 305)
        findings, _ = preflight_side("front", self.photo_side(25), {**AB, "height": 54},
                                     ctx(photo={"assetId": "a", "width": 300, "height": 400}), ApproxMeasurer())
        self.assertFalse([f for f in findings if "DPI" in f["message"]])

    def test_c4_same_photo_at_40mm_warns_at_190_dpi(self):
        self.assertEqual(effective_dpi(300, 40), 190)  # 190.5, half to even as the spec reads it
        findings, _ = preflight_side("front", self.photo_side(40), {**AB, "height": 80},
                                     ctx(photo={"assetId": "a", "width": 300, "height": 400}), ApproxMeasurer())
        dpi = [f for f in findings if "DPI" in f["message"]]
        self.assertEqual([f["severity"] for f in dpi], ["warning"])
        self.assertIn("19", dpi[0]["message"])

    def test_c5_background_short_of_bleed_is_an_error(self):
        s = side(background={"type": "image", "assetId": "x", "extendToBleed": False})
        findings, _ = preflight_side("front", s, AB, ctx(), ApproxMeasurer())
        self.assertEqual([f["severity"] for f in findings], ["error"])
        self.assertIn("bleed", findings[0]["message"])

    def test_c6_five_rows_in_14mm_name_both_measurements(self):
        rows = [{"label": literal(f"Row {i}"), "value": literal("value")} for i in range(5)]
        s = side(el("kv", "Details", "kvTable", frame(5, 5, 40, 14), rows=rows,
                    labelStyle=style(fontSize=8), valueStyle=style(fontSize=9), labelWidth=12, rowGap=1))
        findings, _ = preflight_side("front", s, AB, ctx(), ApproxMeasurer())
        kv = [f for f in findings if f["element"] == "Details"]
        self.assertEqual(kv[0]["severity"], "error")
        self.assertRegex(kv[0]["message"], r"needs \d+\.\dmm .* box is 14\.0mm")

    def test_c7_element_1_4mm_outside_safe_names_1_4mm(self):
        s = side(el("t", "Code", "text", frame(1.6, 10, 20, 4), content=literal("EMP"), style=style(),
                    overflow={"mode": "wrap"}))
        findings, _ = preflight_side("front", s, AB, ctx(), ApproxMeasurer())
        self.assertEqual([(f["severity"], "1.4mm" in f["message"]) for f in findings], [("warning", True)])

    def test_c8_binding_on_40_percent_is_sparse(self):
        s = side(el("t", "Blood", "text", frame(5, 5, 20, 4), content=binding("employee.bloodGroup"), style=style(),
                    overflow={"mode": "wrap"}))
        findings, _ = preflight_side("front", s, AB, ctx(bloodGroup="B+"), ApproxMeasurer(),
                                     {"employee.bloodGroup": 40})
        self.assertIn("Only 40% of employees", findings[0]["message"])

    def test_c9_reprint_reproduces_the_snapshot(self):
        card = self.issue()
        self.assertEqual(card.data_snapshot["employee.job.designation"], "Sewing Operator")
        self.emp.designation = CompanyDesignation.objects.create(company=self.company, title="Line Supervisor")
        self.emp.save()
        reprint = ops.card_context(self.company, card)
        self.assertEqual(reprint["employee"]["job"]["designation"], "Sewing Operator")
        self.assertEqual(C.live_context(self.company, self.emp)["employee"]["job"]["designation"], "Line Supervisor")

    def test_c10_editing_a_printed_template_makes_a_new_version(self):
        card = self.issue()
        profile = OutputProfile.objects.get(company=self.company, sheet="CARD_DIRECT")
        job = ops.submit_job(self.company, [card.uid], profile.uid, render=False)
        ops.render_job(job)
        t = self.standard()
        t.refresh_from_db()
        self.assertTrue(t.locked)
        original = t.front_json
        edited = {**original, "elements": original["elements"][:-1]}
        draft, versioned = ops.save_template(self.company, t, {"front": edited})
        self.assertTrue(versioned)
        self.assertEqual((draft.version, draft.status), (t.version + 1, "DRAFT"))
        t.refresh_from_db()
        self.assertEqual(t.front_json, original)
        card.refresh_from_db()
        self.assertEqual((card.template_id, card.template_version), (t.pk, t.version))

    def test_c11_a_second_active_card_is_refused(self):
        self.issue()
        with self.assertRaises(ops.CardRefused) as caught:
            ops.issue_card(self.company, self.emp)
        self.assertEqual(caught.exception.status, 409)
        first = Card.objects.get(employee=self.emp)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Card.objects.create(company=self.company, employee=self.emp, card_number="ID-2026-09999",
                                template=first.template, template_version=1, data_snapshot={}, status="ISSUED",
                                issued_on=TODAY, expires_on=date(2029, 10, 15), verify_token=ops.new_token())

    def test_c12_a_revoked_card_verifies_as_revoked_with_the_date(self):
        card = self.issue()
        ops.revoke_card(self.company, card, reason="Left the company on 14 October")
        body, code = ops.verify(card.verify_token, "203.0.113.9")
        self.assertEqual((code, body["status"], body["revokedOn"]), (200, "REVOKED", "2026-10-15"))
        self.assertEqual(body["employeeName"], "Md. Rafiqul Islam")

    def test_c13_the_verify_response_carries_nothing_private(self):
        card = self.issue()
        body, code = ops.verify(card.verify_token, "203.0.113.9")
        self.assertEqual((code, body["status"]), (200, "ISSUED"))
        self.assertEqual(set(body), {"status", "employer", "employeeName", "employeeNameBn", "employeeCode",
                                     "designation", "cardNumber", "photoUrl", "issuedOn", "expiresOn", "custom"})
        flat = str(body)
        for secret in ("1990123456789", "01711000000", "B+"):
            self.assertNotIn(secret, flat)
        self.assertEqual(body["expiresOn"], "2029-10-15")

    def test_c14_bengali_is_measured_with_server_metrics(self):
        name = "মোহাম্মদ আশরাফুল আলম সিদ্দিকী"
        prime([(name, "Noto Sans Bengali", 400)])
        real = FontMeasurer().measure(name, 11, 0, "Noto Sans Bengali", 400)
        approx = ApproxMeasurer().measure(name, 11, 0, "Noto Sans Bengali", 400)
        self.assertAlmostEqual(FontMeasurer().measure("Md. Karim Uddin", 11, 0, "IBM Plex Sans", 400), 28.85,
                               delta=0.5)
        self.assertAlmostEqual(real, 54.3, delta=1.5)
        self.assertGreater(abs(real - approx), 5)

    def test_c15_a_ready_job_with_errors_is_refused_by_the_check(self):
        card = self.issue()
        profile = OutputProfile.objects.get(company=self.company, sheet="CARD_DIRECT")
        job = ops.submit_job(self.company, [card.uid], profile.uid, render=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrintJob.objects.filter(pk=job.pk).update(status="READY", preflight_errors=2)


class PropertyTests(Base):
    def test_tokens_are_unique_and_random_looking(self):
        tokens = {ops.new_token() for _ in range(20000)}
        self.assertEqual(len(tokens), 20000)
        self.assertTrue(all(len(t) == 22 and t.isalnum() for t in tokens))
        prefixes = {t[:3] for t in tokens}
        self.assertGreater(len(prefixes), 5000)

    def test_no_verify_response_shows_a_field_not_opted_in(self):
        hidden = CardField.objects.create(company=self.company, key="shiftGroup", label="Shift group", kind="TEXT")
        shown = CardField.objects.create(company=self.company, key="gate", label="Gate", kind="TEXT",
                                         verify_visible=True)
        t = self.standard()
        front = dict(t.front_json)
        front["elements"] = front["elements"] + [
            el("cf1", "Shift", "text", frame(4, 40, 10, 3), content=binding(hidden.path), style=style(fontSize=5),
               overflow={"mode": "truncate"}),
            el("cf2", "Gate", "text", frame(16, 40, 10, 3), content=binding(shown.path), style=style(fontSize=5),
               overflow={"mode": "truncate"})]
        draft, _ = ops.save_template(self.company, t, {"front": front})
        ops.publish_template(self.company, draft, acknowledge_errors=True)
        ops.set_field_values(self.company, self.emp, {"shiftGroup": "Night B", "gate": "Gate 3"})
        card = self.issue()
        body, _ = ops.verify(card.verify_token, "203.0.113.9")
        self.assertEqual(body["custom"], [{"label": "Gate", "value": "Gate 3"}])
        self.assertNotIn("Night B", str(body))

    def test_pii_fields_never_print_or_verify(self):
        f = ops.save_field(self.company, {"key": "nid", "label": "NID", "kind": "TEXT", "isPii": True,
                                          "printable": True, "verifyVisible": True})
        self.assertEqual((f.printable, f.verify_visible), (False, False))
        with self.assertRaises(IntegrityError), transaction.atomic():
            CardField.objects.filter(pk=f.pk).update(printable=True)


# ---------------------------------------------------------------- lifecycle


class LifecycleTests(Base):
    def test_issue_numbers_tokens_and_expires_in_three_years(self):
        card = self.issue()
        self.assertEqual((card.card_number, card.status, card.expires_on), ("ID-2026-00001", "ISSUED",
                                                                             date(2029, 10, 15)))
        self.assertEqual(len(card.verify_token), 22)
        self.assertTrue(CardAudit.objects.filter(card=card, action="CARD_ISSUED").exists())

    def test_issue_without_a_photo_is_refused(self):
        with self.assertRaises(ops.CardRefused) as caught:
            ops.issue_card(self.company, self.emp)
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("photo", caught.exception.errors)

    def test_a_photo_too_small_blocks_issue_with_the_measurement(self):
        self.with_photo(w=120, h=150)
        with self.assertRaises(ops.CardRefused) as caught:
            ops.issue_card(self.company, self.emp)
        self.assertIn("DPI", str(caught.exception))

    def test_revoke_needs_a_reason_and_replace_points_forward(self):
        card = self.issue()
        with self.assertRaises(ops.CardRefused):
            ops.revoke_card(self.company, card, reason="lost")
        new, _ = ops.replace_card(self.company, card, reason="Card damaged in the wash")
        card.refresh_from_db()
        self.assertEqual((card.status, card.replaced_by_id), ("REPLACED", new.pk))
        body, _ = ops.verify(card.verify_token, "203.0.113.9")
        self.assertEqual((body["status"], body["replacedBy"]), ("REPLACED", new.card_number))

    def test_a_card_is_never_deleted(self):
        card = self.issue()
        with self.assertRaises(Exception):
            card.delete()

    def test_the_audit_is_append_only(self):
        self.issue()
        a = CardAudit.objects.first()
        with self.assertRaises(Exception):
            a.save()
        with self.assertRaises(Exception):
            CardAudit.objects.all().delete()

    def test_expiring_and_expired_are_read_against_today(self):
        card = self.issue(expires_on=date(2026, 11, 1))
        self.assertEqual(ops.effective_status(card), "EXPIRING")
        self.assertEqual(ops.effective_status(card, date(2026, 11, 2)), "EXPIRED")

    def test_events_reach_the_outbox_and_the_people_who_act(self):
        from notificationio.models import Notification

        from .models import CardEvent

        boss = make_user(self.company, "boss@rahman.test")
        make_company_admin(boss, self.company)
        card = self.issue(expires_on=date(2026, 11, 1))
        ops.revoke_card(self.company, card, reason="Left the company on 14 October")
        self.assertEqual(list(CardEvent.objects.values_list("name", flat=True).order_by("created_at")),
                         ["CardIssued", "CardRevoked"])
        self.assertTrue(Notification.objects.filter(kind="ID_CARD_REVOKED").exists())
        live = self.issue()
        Card.objects.filter(pk=live.pk).update(expires_on=date(2026, 11, 1))
        self.assertEqual((ops.emit_expiring(self.company), ops.emit_expiring(self.company)), (1, 0))

    def test_resolution_rules_pick_the_template(self):
        from .models import ResolutionRule

        self.assertEqual(ops.template_for(self.company, self.emp)[0].code, "standard")
        ResolutionRule.objects.create(company=self.company, priority=1, label="Sewing operators", template_code="contractor",
                                      condition={"op": "eq", "path": "employee.job.designation",
                                                 "value": "Sewing Operator"})
        t, rule = ops.template_for(self.company, self.emp)
        self.assertEqual((t.code, rule.label), ("contractor", "Sewing operators"))


class PublishTests(Base):
    def test_publish_runs_the_roster_preflight_and_archives_the_previous(self):
        t = self.standard()
        draft, _ = ops.save_template(self.company, t, {"name": "Standard 2027"})
        published, report = ops.publish_template(self.company, draft)
        t.refresh_from_db()
        self.assertEqual((published.status, t.status), ("PUBLISHED", "ARCHIVED"))
        self.assertEqual(report["roster"], 1)

    def test_errors_need_an_acknowledgement_recorded_with_its_name(self):
        t = self.standard()
        front = dict(t.front_json)
        front["elements"] = front["elements"] + [
            el("wide", "Too long", "text", frame(4, 30, 8, 3), content=literal("A much longer line than fits"),
               style=style(fontSize=8), overflow={"mode": "shrink", "minFontSize": 7})]
        draft, _ = ops.save_template(self.company, t, {"front": front})
        with self.assertRaises(ops.CardRefused) as caught:
            ops.publish_template(self.company, draft)
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("does not fit its box", str(caught.exception.detail["findings"]))
        published, _ = ops.publish_template(self.company, draft, acknowledge_errors=True)
        self.assertGreater(published.publish_findings["errors"], 0)

    def test_a_malformed_side_is_refused_on_save(self):
        with self.assertRaises(ops.CardRefused) as caught:
            ops.save_template(self.company, self.standard(), {"front": {"elements": [{"type": "blob"}]}})
        self.assertIn("unknown type", str(caught.exception))


class PrintTests(Base):
    def profile(self, sheet="CARD_DIRECT"):
        return OutputProfile.objects.filter(company=self.company, sheet=sheet).first()

    def test_render_produces_a_pdf_with_its_sha_and_locks_the_template(self):
        card = self.issue()
        job = ops.render_job(ops.submit_job(self.company, [card.uid], self.profile().uid, render=False))
        self.assertEqual((job.status, job.artifact_pages), ("READY", 2))
        with job.artifact.open("rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(len(job.artifact_sha256), 64)
        ops.mark_printed(self.company, job)
        card.refresh_from_db()
        self.assertEqual((card.status, card.print_count), ("ACTIVE", 1))

    def test_a_barcode_prints_full_height(self):
        """WeasyPrint once collapsed a percentage-sized barcode to a line."""
        from .services.engine import resolve_side
        from .services.render import preview_png

        bar = el("bc", "Barcode", "barcode", frame(5, 5, 40, 10), value=literal("EMP-0001"), quietZone=2)
        ab = {"width": 54.0, "height": 30.0, "bleed": 2.0, "safe": 3.0, "radius": 3.18}
        png_bytes = preview_png(resolve_side(side(bar), ctx()), ab, lambda ref: None, dpi=100)
        img = Image.open(io.BytesIO(png_bytes)).convert("L")
        px = lambda mm: round(mm / 25.4 * 100)  # noqa: E731
        dark_rows = sum(1 for y in range(px(5), px(15))
                        if sum(img.getpixel((x, y)) < 100 for x in range(px(5), px(45))) > 20)
        self.assertGreater(dark_rows, px(10) * 0.8)

    def test_an_a4_sheet_and_png_zip(self):
        second = make_employee(self.company, "EMP-0002", "Nasima Akter", designation=self.sewing, status="ACTIVE")
        cards = [self.issue(), self.issue(second)]
        a4 = ops.render_job(ops.submit_job(self.company, [c.uid for c in cards], self.profile("A4").uid,
                                           include_warnings=True, render=False))
        self.assertEqual(a4.status, "READY", a4.failure_reason)
        import fitz

        with a4.artifact.open("rb") as f:
            doc = fitz.open(stream=f.read(), filetype="pdf")
        # Both cards on the sheet, and the backs on the second page.
        self.assertIn("Nasima Akter", doc[0].get_text())
        self.assertIn("Md. Rafiqul Islam", doc[0].get_text())
        self.assertIn("EMP-0002", doc[1].get_text())
        pngs = ops.render_job(ops.submit_job(self.company, [cards[0].uid], self.profile("PNG").uid,
                                             include_warnings=True, render=False))
        self.assertEqual(pngs.status, "READY", pngs.failure_reason)
        self.assertTrue(pngs.artifact.name.endswith(".zip"))

    def test_warnings_are_skipped_unless_included(self):
        card = self.issue()
        t = card.template
        front = dict(t.front_json)
        front["elements"] = front["elements"] + [
            el("edge", "Edge note", "text", frame(1.2, 30, 10, 3), content=literal("x"), style=style(fontSize=5),
               overflow={"mode": "wrap"})]
        CardTemplate.objects.filter(pk=t.pk).update(front_json=front)
        with self.assertRaises(ops.CardRefused):
            ops.submit_job(self.company, [card.uid], self.profile().uid, render=False)
        job = ops.submit_job(self.company, [card.uid], self.profile().uid, include_warnings=True, render=False)
        self.assertEqual(job.card_count, 1)

    def test_a_draft_or_revoked_card_does_not_print(self):
        card = self.issue()
        ops.revoke_card(self.company, card, reason="Reported stolen at the gate")
        with self.assertRaises(ops.CardRefused) as caught:
            ops.submit_job(self.company, [card.uid], self.profile().uid, render=False)
        self.assertIn("Only issued or active", str(caught.exception))


# ---------------------------------------------------------------------- api


@override_settings(MEDIA_ROOT=MEDIA, APP_URL="https://app.example.test")
class ApiTests(ApiMixin, Base):
    def setUp(self):
        super().setUp()
        self.admin = make_user(self.company, "owner@rahman.test")
        make_company_admin(self.admin, self.company)
        self.clerk = make_user(self.company, "clerk@rahman.test")

    def test_gallery_lists_the_roster_with_contexts(self):
        body = self.client_for(self.admin).get(f"{API}/gallery").json()
        row = body["rows"][0]
        self.assertEqual((row["code"], row["status"], row["missing"]), ("EMP-0001", "NOT_ISSUED", ["photo"]))
        self.assertIn(row["template"]["uid"], body["templates"])
        self.assertEqual(row["context"]["employee"]["fullName"], "Md. Rafiqul Islam")
        self.assertEqual(body["counts"]["MISSING"], 1)

    def test_photo_upload_issue_and_public_verify(self):
        client = self.client_for(self.admin)
        up = client.post(f"{API}/employees/EMP-0001/photo", {"file": png(600, 750)}, format="multipart")
        self.assertEqual(up.status_code, 201, up.content)
        img = self.client.get(up.json()["url"])
        self.assertEqual((img.status_code, img["Content-Type"]), (200, "image/jpeg"))
        made = client.post(f"{API}/cards", {"employeeCode": "EMP-0001"}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        card = made.json()["card"]
        self.assertTrue(card["verifyUrl"].startswith("https://app.example.test/verify/"))
        token = card["verifyUrl"].rsplit("/", 1)[1]
        public = self.client.get(f"/api/v1/public/idcards/verify/{token}")
        self.assertEqual((public.status_code, public.json()["status"]), (200, "ISSUED"))
        self.assertEqual(self.client.get(public.json()["photoUrl"]).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/public/idcards/verify/AAAAAAAAAAAAAAAAAAAAAA").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/public/idcard-media/forged").status_code, 404)
        scan = CardAudit.objects.filter(action="VERIFY_SCANNED").first()
        self.assertIsNone(scan.actor_id)
        self.assertTrue(scan.actor_ip)

    def test_verification_is_rate_limited(self):
        card = self.issue()
        for _ in range(50):
            self.client.get(f"/api/v1/public/idcards/verify/{card.verify_token}")
        self.assertEqual(self.client.get(f"/api/v1/public/idcards/verify/{card.verify_token}").status_code, 429)

    def test_each_gate_needs_its_permission(self):
        client = self.client_for(self.clerk)
        self.with_photo()
        self.assertEqual(client.post(f"{API}/cards", {"employeeCode": "EMP-0001"}, format="json").status_code, 403)
        give(self.clerk, self.company, "issue_cards")
        made = client.post(f"{API}/cards", {"employeeCode": "EMP-0001"}, format="json")
        self.assertEqual(made.status_code, 201)
        uid = made.json()["card"]["uid"]
        self.assertEqual(client.post(f"{API}/cards/{uid}/revoke", {"reason": "Left the company"},
                                     format="json").status_code, 403)
        profile = OutputProfile.objects.filter(company=self.company, sheet="CARD_DIRECT").first()
        give(self.clerk, self.company, "print_cards")
        refused = client.post(f"{API}/print-jobs", {"cardUids": [uid], "profileUid": str(profile.uid),
                                                    "includeWarnings": True}, format="json")
        self.assertEqual(refused.status_code, 403)
        self.assertIn("override", refused.content.decode())

    def test_patching_a_published_template_answers_with_the_new_draft(self):
        client = self.client_for(self.admin)
        t = self.standard()
        r = client.patch(f"{API}/templates/{t.uid}", {"name": "Standard v2"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["versioned"], r.json()["version"], r.json()["status"]), (True, 2, "DRAFT"))
        again = client.patch(f"{API}/templates/{t.uid}", {"name": "Standard v2b"}, format="json").json()
        self.assertEqual(again["uid"], r.json()["uid"])  # the same draft, not a third version
        pf = client.post(f"{API}/templates/{again['uid']}/preflight", {}, format="json").json()
        self.assertIn("errors", pf)

    def test_print_wizard_check_and_download(self):
        client = self.client_for(self.admin)
        card = self.issue()
        check = client.post(f"{API}/print-check", {"cardUids": [str(card.uid)]}, format="json").json()
        self.assertEqual(check["blocked"], 0)
        profile = OutputProfile.objects.filter(company=self.company, sheet="CARD_DIRECT").first()
        with self.captureOnCommitCallbacks(execute=False):
            made = client.post(f"{API}/print-jobs", {"cardUids": [str(card.uid)], "profileUid": str(profile.uid),
                                                     "includeWarnings": True}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        job = PrintJob.objects.get(uid=made.json()["uid"])
        ops.render_job(job)
        dl = client.get(f"{API}/print-jobs/{job.uid}/download")
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(len(dl["X-Artifact-SHA256"]), 64)

    def test_another_companys_card_is_not_found(self):
        other = make_company("Other Ltd")
        stranger = make_user(other, "boss@other.test")
        make_company_admin(stranger, other)
        card = self.issue()
        self.assertEqual(self.client_for(stranger).get(f"{API}/cards/{card.uid}").status_code, 404)
