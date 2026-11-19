import { ref, unref } from 'vue';
import { storeToRefs } from 'pinia';
import { useUserInfo } from '/@/stores/userInfo';
import websocket from '/@/utils/websocket';

/**
 * 头像上的在线状态：离线时头像外面套一个"重试"确认气泡，点重试重连 websocket
 * 顶栏头像（经典、横向、分栏布局）和侧栏底部头像（侧边栏布局）共用
 */
export function useOnlineReconnect() {
	const { isSocketOpen } = storeToRefs(useUserInfo());
	const onlinePopoverRef = ref();
	const onlineConfirmEvent = () => {
		if (!isSocketOpen.value) {
			websocket.is_reonnect = true;
			websocket.reconnect_current = 1;
			websocket.reconnect();
		}
		// 手动隐藏弹出
		unref(onlinePopoverRef).popperRef?.delayHide?.();
	};
	return { isSocketOpen, onlinePopoverRef, onlineConfirmEvent };
}
