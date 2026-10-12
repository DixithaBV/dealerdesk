from rest_framework.response import Response
from rest_framework.views import APIView

from .service import run_sync


class SupplierSyncView(APIView):
    def post(self, request):
        return Response(run_sync())
