"""
Product Lookup - Web-based SKU verification for ambiguous items

When the AI is uncertain about a product, attempt to verify by:
1. Searching vendor website for SKU
2. Extracting product details from search results
3. Using that context to improve categorization

This reduces misclassifications like "HOT ROD" → hot dogs instead of snacks.
"""
import re
from typing import Optional, Dict, Any
from decimal import Decimal

import httpx
import structlog

from packages.common.config import get_settings

logger = structlog.get_logger()


class ProductLookup:
    """
    Look up products on vendor websites to improve categorization accuracy.

    Used when AI confidence is low or when categorization seems ambiguous.

    DISABLED BY DEFAULT - Enable with CATEGORIZATION_WEB_LOOKUP_ENABLED=true
    (Vendor websites may block scraping, rate-limit, or change structure)
    """

    def __init__(self):
        """Initialize with settings."""
        self.settings = get_settings()

    # Vendor-specific search URL patterns
    VENDOR_SEARCH_URLS = {
        "Costco": "https://www.costco.ca/CatalogSearch?keyword={sku}",
        "GFS": "https://www.gfs.com/en-us/search?searchTerm={sku}",
        "Gordon Food Service": "https://www.gfs.com/en-us/search?searchTerm={sku}",
        "Superstore": "https://www.atlanticsuperstore.ca/search?search-bar={sku}",
        "Wholesale Club": "https://www.wholesaleclub.ca/search?search-bar={sku}",
        # Add more vendors as needed
    }

    async def lookup_product(
        self,
        vendor: str,
        sku: str,
        raw_description: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt to look up product details from vendor website.

        Args:
            vendor: Vendor name (e.g., "Costco")
            sku: Vendor SKU code
            raw_description: Raw description from receipt

        Returns:
            Dictionary with product details if found, None if lookup disabled/failed
        """
        # Check if web lookup is enabled
        if not self.settings.categorization_web_lookup_enabled:
            logger.debug("web_lookup_disabled",
                        vendor=vendor,
                        sku=sku,
                        message="Set CATEGORIZATION_WEB_LOOKUP_ENABLED=true to enable")
            return None

        # Check if we have a search URL for this vendor
        search_url_template = self.VENDOR_SEARCH_URLS.get(vendor)

        if not search_url_template:
            logger.debug("vendor_lookup_not_supported",
                        vendor=vendor,
                        message=f"No search URL configured for {vendor}")
            return None

        search_url = search_url_template.format(sku=sku)

        logger.info("product_lookup_started",
                   vendor=vendor,
                   sku=sku,
                   url=search_url)

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.categorization_web_lookup_timeout,
                follow_redirects=True
            ) as client:
                response = await client.get(
                    search_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; CurlysBooks/1.0; +https://books.curlys.ca)",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                )

                if response.status_code != 200:
                    logger.warning("product_lookup_failed",
                                  vendor=vendor,
                                  sku=sku,
                                  status_code=response.status_code)
                    return None

                # Extract product details from HTML
                html = response.text
                product_info = self._extract_product_info(html, vendor, sku, raw_description)

                if product_info:
                    logger.info("product_lookup_success",
                               vendor=vendor,
                               sku=sku,
                               found_name=product_info.get("product_name"))
                    return product_info
                else:
                    logger.info("product_lookup_no_match",
                               vendor=vendor,
                               sku=sku,
                               message="SKU not found on vendor website")
                    return None

        except httpx.TimeoutException:
            logger.warning("product_lookup_timeout",
                          vendor=vendor,
                          sku=sku,
                          timeout=self.settings.categorization_web_lookup_timeout)
            return None

        except Exception as e:
            logger.error("product_lookup_error",
                        vendor=vendor,
                        sku=sku,
                        error=str(e),
                        exc_info=True)
            return None

    def _extract_product_info(
        self,
        html: str,
        vendor: str,
        sku: str,
        raw_description: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract product information from vendor website HTML.

        This is vendor-specific parsing logic.

        Args:
            html: HTML response from vendor website
            vendor: Vendor name
            sku: SKU being searched
            raw_description: Original description from receipt

        Returns:
            Product information dict or None
        """
        # Generic extraction - look for common patterns
        product_info = {}

        # Try to find product name in various HTML structures
        patterns = [
            # Costco patterns
            r'<h1[^>]*>([^<]+)</h1>',
            r'<span[^>]*class="[^"]*product[^"]*name[^"]*"[^>]*>([^<]+)</span>',
            r'"product_name"\s*:\s*"([^"]+)"',

            # Generic e-commerce patterns
            r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"',
            r'<title>([^<]+)</title>',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                product_name = match.group(1).strip()

                # Verify this actually looks like a product (not a generic page title)
                if len(product_name) > 5 and not any(x in product_name.lower() for x in ['costco', 'search results', 'error', 'not found']):
                    product_info["product_name"] = product_name
                    break

        # Try to extract brand
        brand_patterns = [
            r'"brand"\s*:\s*"([^"]+)"',
            r'<span[^>]*class="[^"]*brand[^"]*"[^>]*>([^<]+)</span>',
        ]

        for pattern in brand_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                product_info["brand"] = match.group(1).strip()
                break

        # Try to extract category/department
        category_patterns = [
            r'"category"\s*:\s*"([^"]+)"',
            r'<span[^>]*class="[^"]*category[^"]*"[^>]*>([^<]+)</span>',
        ]

        for pattern in category_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                product_info["category_hint"] = match.group(1).strip()
                break

        # Only return if we found at least a product name
        if "product_name" in product_info:
            return product_info

        # If nothing found, check if SKU appears in HTML at all
        # (might be behind authentication or different page structure)
        sku_pattern = re.escape(sku)
        if re.search(sku_pattern, html, re.IGNORECASE):
            logger.debug("product_lookup_sku_found_but_cant_parse",
                        vendor=vendor,
                        sku=sku,
                        message="SKU appears in HTML but couldn't extract product details")

        return None


# Singleton instance
product_lookup = ProductLookup()
