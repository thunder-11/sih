"""Single composition root for the current versioned HTTP surface."""

from fastapi import APIRouter

from app.api.routes.system import router as system_router
from app.api.routes.workflow import router as workflow_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.ml_data import router as ml_data_router
from app.api.routes.ml_inference import router as ml_inference_router
from app.api.routes.ml_monitoring import router as ml_monitoring_router
from app.api.routes.operations import router as operations_router
from app.api.routes.investigator_operations import router as investigator_operations_router
from auth.router import router as auth_router
from routers.complaints import router as complaints_router
from routers.traces import router as traces_router, trace_read_router
from routers.api import alerts_router, cases_router, dashboard_router, notices_router, reports_router, vasp_router


api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(auth_router)
api_router.include_router(workflow_router)
api_router.include_router(analytics_router)
api_router.include_router(ml_data_router)
api_router.include_router(ml_inference_router)
api_router.include_router(ml_monitoring_router)
api_router.include_router(operations_router)
api_router.include_router(investigator_operations_router)
api_router.include_router(complaints_router)
api_router.include_router(traces_router)
api_router.include_router(trace_read_router)
api_router.include_router(cases_router)
api_router.include_router(alerts_router)
api_router.include_router(vasp_router)
api_router.include_router(notices_router)
api_router.include_router(reports_router)
api_router.include_router(dashboard_router)
