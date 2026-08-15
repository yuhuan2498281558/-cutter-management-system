# -*- coding: utf-8 -*-

"""
@Remark: 盾构项目管理和刀具管理路由配置
"""
from django.urls import path, include
from rest_framework import routers
from dvadmin.utils.permission import AnonymousUserPermission
from .views import (
    ProjectInfoViewSet,
    ToolCategoryViewSet,
    ToolCostViewSet,
    ToolInfoViewSet,
    WarehouseOpeningBasicInfoViewSet,
    ToolChangeDetailViewSet,
    WearTypeDictViewSet,
    AbnormalCauseDictViewSet,
    ShieldMachineBasicInfoViewSet,
    CutterPositionInfoViewSet,
    CutterModelMappingViewSet,
    CutterImageAnnotationViewSet,
    ShieldTunnelingDataViewSet,
    ToolLifePredictionViewSet,
    StratumBasicInfoViewSet,
)
from .analysis_views import AnalysisViewSet
from .mobile_views import AdminMobileTaskViewSet, MobileMeViewSet, MobileTaskViewSet, ToolLifecycleViewSet

# 使用SimpleRouter自动生成标准CRUD路由
shield_url = routers.SimpleRouter()

# 注册路由（统一使用下划线命名）
shield_url.register(r'project', ProjectInfoViewSet)  # 项目信息管理
shield_url.register(r'tool_category', ToolCategoryViewSet)  # 刀具类型字典
shield_url.register(r'tool_cost', ToolCostViewSet)  # 刀具成本信息
shield_url.register(r'tool_info', ToolInfoViewSet)  # 刀具信息管理
shield_url.register(r'warehouse_opening', WarehouseOpeningBasicInfoViewSet)  # 换刀基本信息
shield_url.register(r'tool_change_detail', ToolChangeDetailViewSet)  # 换刀明细（整合版）
shield_url.register(r'wear_type_dict', WearTypeDictViewSet)  # 磨损类型字典
shield_url.register(r'abnormal_cause_dict', AbnormalCauseDictViewSet)  # 异常原因字典
# shield_url.register(r'stratum_type_dict', StratumTypeDictViewSet)  # 地层类型字典（已废弃，使用系统字典）
shield_url.register(r'shield_machine_basic_info', ShieldMachineBasicInfoViewSet)  # 盾构机基本信息
shield_url.register(r'cutter_position_info', CutterPositionInfoViewSet)  # 刀位信息
shield_url.register(r'stratum_basic_info', StratumBasicInfoViewSet)  # 地层基本信息
shield_url.register(r'analysis', AnalysisViewSet, basename='analysis')  # 数据分析

shield_url.register(r'cutter_model_mapping', CutterModelMappingViewSet)
shield_url.register(r'cutter_image_annotation', CutterImageAnnotationViewSet)
shield_url.register(r'tunneling_data', ShieldTunnelingDataViewSet)
shield_url.register(r'tool_life_prediction', ToolLifePredictionViewSet)
shield_url.register(r'mobile/task_manage', AdminMobileTaskViewSet, basename='mobile-task-manage')
shield_url.register(r'mobile/me', MobileMeViewSet, basename='mobile-me')
shield_url.register(r'mobile/tasks', MobileTaskViewSet, basename='mobile-tasks')
shield_url.register(r'mobile/tool_lifecycle', ToolLifecycleViewSet, basename='mobile-tool-lifecycle')

urlpatterns = [
    path(
        'mobile/task_manage/assign_options/',
        AdminMobileTaskViewSet.as_view({'get': 'assign_options'}),
        name='mobile-task-manage-assign-options-explicit',
    ),
    path(
        'mobile/task_manage/recorder_options/',
        AdminMobileTaskViewSet.as_view({'get': 'recorder_options'}),
        name='mobile-task-manage-recorder-options-explicit',
    ),
    path(
        'mobile/task_manage/<int:pk>/approval_detail/',
        AdminMobileTaskViewSet.as_view({'get': 'approval_detail'}),
        name='mobile-task-manage-approval-detail-explicit',
    ),
    path(
        'tool_change_detail/home_warnings/',
        ToolChangeDetailViewSet.as_view(
            {'get': 'home_warnings'},
            permission_classes=[AnonymousUserPermission],
        ),
        name='tool-change-detail-home-warnings',
    ),
    path('', include(shield_url.urls)),
]
