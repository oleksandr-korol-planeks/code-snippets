import json
import logging

from django.conf import settings
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from settings.models import GoogleMerchantConfig


logger = logging.getLogger("django")


class GoogleMerchantService:
    def __init__(self) -> None:
        """
        Initializes an instance of the class with a GoogleMerchantConfig object,
        from which it extracts account credentials to authenticate with the Google Content API.
        Instantiates an object of the Google Content API service to use in the class.
        """

        self.config = GoogleMerchantConfig.objects.first()
        self.merchant_id = self.config.merchant_id
        self.feed_id = self.config.feed_id
        self.service = build(
            "content",
            "v2.1",
            credentials=Credentials.from_service_account_info(json.loads(json.dumps(self.config.account))),
        )

    def upload_item_to_google_merchant(self, item) -> None:
        """
        Uploads the given item to the Google Merchant Centre using the Content API v2.1.
        The item is first converted into a data structure that is compatible with the
        Google Content API. The item's delivery options are then used to construct
        a list of shipping options for the item. The item is then inserted into the
        Google Merchant Centre using the credentials stored in the GoogleMerchantConfig
        model.

        Args:
            item (Item): The item to be uploaded to the Google Merchant Centre
        """
        country_map = {"EU": "EU", "USA": "USA", "UK": "GB", "WORLD": "001"}
        shipping = [
            {
                "country": country_map[i.region],
                "price": {"value": i.price or 0, "currency": str(item.currency)},
            }
            for i in item.delivery_options.filter(region="UK")
        ]
        product_data = {
            "offerId": item.ref,
            "channel": "online",  # indicates the item is sold through the online store
            "title": item.title,
            "identifierExists": False,
            "description": item.description,
            "link": f"{settings.SITE_URL}{item.sf_url}",
            "imageLink": item.image(),
            "additionalImageLinks": [i.image.url for i in item.images.all()],
            "material": item.item_materials()[0] if item.item_materials() else "",
            "contentLanguage": "en",
            "targetCountry": "GB",
            "condition": "used",  # condition of the item, i.e. new, used, refurbished
            "availability": "in_stock",  # availability of the item
            "shipping": shipping,  # list of shipping options for the item
            "price": {"value": item.price, "currency": str(item.currency)},
        }
        try:
            self.service.products().insert(
                merchantId=self.merchant_id, body=product_data
            ).execute()
        except Exception as error:
            logging.error(f"Error adding item: {error}")

    def delete_item_from_google_merchant(self, item) -> None:
        try:
            self.service.products().delete(merchantId=self.merchant_id, productId=f"online:en:GB:{item.ref}").execute()
        except Exception as error:
            logging.error(f"Error deleting item: {error}")

    def get_statistics(self) -> dict:
        """
        Get statistics about the items in the Google Merchant Centre.

        Returns:
            dict: dictionary containing information about the items in the Google Merchant Centre,
            including the total number of items, the number of items that have been disapproved,
            and the number of available items.
        """
        try:
            statuses = self.service.productstatuses().list(
                merchantId=self.merchant_id,
            ).execute().get("resources")
            all_items = len(statuses)
            disapproved = len([i for i in statuses if i["destinationStatuses"][0]["status"] == "disapproved"])
            available = all_items - disapproved
            return {
                "all": all_items,
                "disapproved": disapproved,
                "available": available,
            }
        except Exception as error:
            logging.error("Error getting statistics: %s", error)
