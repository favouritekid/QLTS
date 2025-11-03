# flake8: noqa: F401
# app/services/__init__.py

# Dòng này sẽ import các module vào package services,
# giúp chúng ta có thể gọi `services.user_service`, `services.insights_service`...
# hực hiện đúng vai trò của mình là điều phối request đến service và trả về response, đồng thời xử lý các validation đầu vào cơ bản và phân quyền
from . import (
    assignment_service,
    config_service,
    insights_service,
    lead_service,
    organization_service,
    pipeline_service,
    user_service,
)
