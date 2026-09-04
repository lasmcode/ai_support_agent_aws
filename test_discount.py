from dotenv import load_dotenv
load_dotenv()
from main import calculate_loyalty_discount

result = calculate_loyalty_discount(
    loyalty_points=4250,
    tier="Gold",
    order_total=150.0,
    product_category="standard",
)
print(result)