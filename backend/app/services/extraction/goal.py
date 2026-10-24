PRODUCT_FIELDS = [
    "title", "seller", "price", "currency", "moq", "description", "specifications",
    "model", "material", "voltage", "bluetooth", "wifi", "battery", "battery_type",
    "certification_claims", "image", "source_url",
]

PRODUCT_GOAL = (
    "This is a product detail page. Extract only information that is visibly present on "
    "the page. Return a single JSON object with exactly these keys: "
    + ", ".join(PRODUCT_FIELDS)
    + ". Use null for any value that is not shown on the page; never guess or infer. "
    "'price' is the displayed unit price (keep any range text), "
    "'currency' the displayed currency, 'moq' the minimum order quantity, "
    "'specifications' an object of attribute name to value, "
    "'certification_claims' a list of certifications the seller claims (e.g. CE, FCC, BIS). "
    "'image' is the absolute URL of the main photo of this exact product, not a logo, "
    "icon, or recommended product. Resolve relative photo URLs against the listing URL. "
    "Do not log in, solve CAPTCHAs, or bypass any access restriction. If the page is not a "
    'product page or cannot be viewed, return {"status": "failure", "reason": "<why>"}.'
)
