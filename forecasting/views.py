from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Inventory
from core.exceptions import APIError

from . import reorder as R


class ForecastView(APIView):
    def get(self, request, sku):
        f = R.load_forecast(str(settings.ML_DIR)).get(sku)
        if not f:
            raise APIError(404, "NOT_FOUND", f"No forecast for SKU {sku}.")
        return Response({"sku": sku, "forecast": [{"week_start": w, "forecast_units": f[w]} for w in R.WEEKS]})


class ReorderSuggestionsView(APIView):
    def get(self, request):
        fc = R.load_forecast(str(settings.ML_DIR))
        leads = R.load_lead_times(str(settings.DATA_DIR))
        recent = R.load_recent_sales(str(settings.DATA_DIR))
        stock = dict(Inventory.objects.filter(product__sku__in=[s for s, _ in leads])
                     .values_list("product__sku", "quantity"))  # live stock, read at request time
        results = [R.reorder_entry(s, L, fc[s], recent.get(s, []), stock.get(s, 0)) for s, L in leads]
        return Response({"results": results})
