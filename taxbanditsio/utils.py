import os, time, json, hmac, hashlib, base64, requests
from django.conf import settings


def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def generate_jwt():
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": settings.TAXBANDITS_CLIENT_ID,
        "sub": settings.TAXBANDITS_CLIENT_ID,
        "aud": settings.TAXBANDITS_USER_TOKEN,
        "iat": int(time.time()),
        "exp": int(time.time()) + 18000,
    }

    header_b64 = base64url_encode(json.dumps(header).encode())
    payload_b64 = base64url_encode(json.dumps(payload).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()

    signature = hmac.new(
        settings.TAXBANDITS_CLIENT_SECRET.encode(), signing_input, hashlib.sha256
    ).digest()
    signature_b64 = base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def get_access_token():
    # r = redis.from_url(settings.CELERY_BROKER_URL)
    # cached_token = r.get("taxbandits_access_token")
    # if cached_token:
    #     return cached_token.decode("utf-8")

    jwt = generate_jwt()
    headers = {
        "Authentication": jwt,
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(settings.TAXBANDITS_OAUTH_URL, headers=headers)
    resp.raise_for_status()
    token = resp.json()["AccessToken"]
    # r.set("taxbandits_access_token", token, ex=18000)
    return token


def list_businesses(access_token, page=1, page_size=10, from_date=None, to_date=None):
    params = []
    params.append(f"Page={page}")
    params.append(f"PageSize={page_size}")
    if from_date:
        params.append(f"FromDate={from_date}")
    if to_date:
        params.append(f"ToDate={to_date}")
    query = "&".join(params)
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Business/List?{query}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def get_business(access_token, business_id):

    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Business/Get?BusinessId={business_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def create_business(access_token, business_data):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Business/Create"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.post(url, headers=headers, json=business_data)
    resp.raise_for_status()
    return resp.json()


def delete_business(access_token, business_id, ein_or_ssn, is_force_delete=False):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Business/Delete?BusinessId={business_id}&EINOrSSN={ein_or_ssn}&isForceDelete={str(is_force_delete).lower()}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.delete(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def update_business(access_token, business_data):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Business/Update"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.put(url, headers=headers, json=business_data)
    resp.raise_for_status()
    return resp.json()


# for form 940
def get_940_form_list(access_token, business_id):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form940/List?BusinessId={business_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def get_form_940_details(access_token, submission_id, record_ids):
    params = [f"SubmissionId={submission_id}", f"RecordIds={record_ids}"]
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form940/Get?{'&'.join(params)}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def create_form_940(access_token, payload: dict):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form940/Create"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def start_8453_emp(access_token, payload: dict):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form8453emp/RequestByURLPayer"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def get_signature_status(access_token, record_id):
    url = (
        f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form8453emp/Status?RecordId={record_id}"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def post_form_940_transmit(access_token, payload: dict):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form940/Transmit"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def get_form_940_pdf(access_token, submission_id, record_ids):
    params = [f"SubmissionId={submission_id}", f"RecordIds={record_ids}"]
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form940/GetPDF?{'&'.join(params)}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


# 941 form utils
def get_941_form_list(access_token, business_id):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form941/List?BusinessId={business_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def get_941_form_details(access_token, submission_id):
    url = (
        f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form941/Get?SubmissionId={submission_id}"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def create_form_941(access_token, payload: dict):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form941/Create"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def get_941_form_validate(access_token, submission_id, record_ids):
    params = [f"SubmissionId={submission_id}", f"RecordIds={record_ids}"]
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form941/Validate?{'&'.join(params)}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def post_form_941_transmit(access_token, payload: dict):
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form941/Transmit"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def get_941_form_pdf(access_token, submission_id, record_ids):
    params = [f"SubmissionId={submission_id}", f"RecordIds={record_ids}"]
    url = f"{settings.TAXBANDITS_API_URL}/v1.7.3/Form941/GETPDF?{'&'.join(params)}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Referer": settings.TAXBANDITS_DOMAIN_REFERENCE_ID,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()
