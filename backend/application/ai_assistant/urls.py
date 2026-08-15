"""
URL路由配置
"""

from django.urls import path
from . import views

# async 视图不能用 csrf_exempt() 包装，直接设属性跳过 CSRF 检查
views.chat_stream.csrf_exempt = True

urlpatterns = [
    path('chat/', views.chat, name='ai_chat'),
    path('chat/stream/', views.chat_stream, name='ai_chat_stream'),
    path('health/', views.health_check, name='ai_health'),
    path('reset/', views.reset_conversation, name='ai_reset'),
]
