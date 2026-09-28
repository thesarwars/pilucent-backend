from .constructions import constructions
from .property_bookkeeping import property_bookkeeping
from .real_estate import real_estate
from .ecommerce import ecommerce
from .fashion_apparel import fashion_apparel
from .food_beverage import food_beverage
from .hardware_electronics import hardware_electronics
from .legal_bookkeeping import legal_bookkeeping
from .agriculture_industry import agriculture_industry
from .automobile_industry import automobile_industry
from .education_training_industry import education_training_industry
from .restaurant_hotel import restaurant_hotel
from .sports_fitness import sports_fitness
from .travel_tourism import travel_tourism
from .retail_wholesale import retail_wholesale
from .medical_pharmaceutical import medical_pharmaceutical
from .marketing_advertising import marketing_advertising
from .financial_services import financial_services
from .business_services_consulting import business_services_consulting
from .brokerage_house import brokerage_house


chart_of_accounts = (
    constructions
    + property_bookkeeping
    + real_estate
    + ecommerce
    + fashion_apparel
    + food_beverage
    + hardware_electronics
    + legal_bookkeeping
    + agriculture_industry
    + automobile_industry
    + education_training_industry
    + restaurant_hotel
    + sports_fitness
    + travel_tourism
    + retail_wholesale
    + medical_pharmaceutical
    + marketing_advertising
    + financial_services
    + business_services_consulting
    + brokerage_house
)
