<template>
	<div class="layout-aside-user">
		<!-- 头像带在线状态点；离线时悬停出现"重试"，与原来顶栏头像一致 -->
		<el-popconfirm
			v-if="!isSocketOpen"
			width="250"
			ref="onlinePopoverRef"
			:confirm-button-text="$t('message.user.retry')"
			:icon="InfoFilled"
			trigger="hover"
			:title="$t('message.user.onlinePrompt')"
			@confirm="onlineConfirmEvent"
		>
			<template #reference>
				<el-badge is-dot class="layout-aside-user-status is-offline">
					<img :src="userInfos.avatar || headerImage" class="layout-aside-user-avatar" alt="" />
				</el-badge>
			</template>
		</el-popconfirm>
		<el-badge v-else is-dot class="layout-aside-user-status">
			<img :src="userInfos.avatar || headerImage" class="layout-aside-user-avatar" alt="" />
		</el-badge>
		<div class="layout-aside-user-who">
			<b>{{ userInfos.username === '' ? 'common' : userInfos.username }}</b>
			<small v-if="roleNames">{{ roleNames }}</small>
		</div>
		<UserDropdown trigger="click" placement="top-end">
			<button type="button" class="layout-aside-user-more">
				<el-icon :size="16"><ele-MoreFilled /></el-icon>
			</button>
		</UserDropdown>
	</div>
</template>

<script setup lang="ts" name="layoutAsideUser">
import { defineAsyncComponent, computed } from 'vue';
import { storeToRefs } from 'pinia';
import { InfoFilled } from '@element-plus/icons-vue';
import { useUserInfo } from '/@/stores/userInfo';
import headerImage from '/@/assets/img/headerImage.png';
import { useOnlineReconnect } from '/@/layout/navBars/breadcrumb/useOnlineReconnect';

// 引入组件
const UserDropdown = defineAsyncComponent(() => import('/@/layout/navBars/breadcrumb/userDropdown.vue'));

// 定义变量内容
const { userInfos } = storeToRefs(useUserInfo());
const { isSocketOpen, onlinePopoverRef, onlineConfirmEvent } = useOnlineReconnect();

// 角色名：一个用户可有多个角色
const roleNames = computed(() =>
	(userInfos.value.role_info || [])
		.map((role: { name?: string }) => role?.name)
		.filter(Boolean)
		.join('、')
);
</script>

<style scoped lang="scss">
// 头像左边离侧栏 12px（侧栏内边距 8px + 4px），中线与菜单图标对齐
.layout-aside-user {
	display: flex;
	align-items: center;
	gap: 10px;
	margin-top: auto;
	padding: 8px 0 0 4px;
	border-top: 1px solid var(--dv-divider);
	&-status {
		flex: none;
		display: flex;
		// 在线状态点放在头像右下角，外圈一道侧栏底色描边
		:deep(.el-badge__content.is-dot) {
			top: auto;
			bottom: 1px;
			right: 5px;
			width: 8px;
			height: 8px;
			border: none;
			background-color: var(--dv-success);
			box-shadow: 0 0 0 2px var(--dv-side-bg);
		}
		&.is-offline :deep(.el-badge__content.is-dot) {
			background-color: var(--dv-text-muted);
		}
	}
	&-avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		object-fit: cover;
		background: var(--dv-raise);
		box-shadow: var(--dv-shadow-raised);
	}
	&-who {
		flex: 1;
		min-width: 0;
		display: grid;
		line-height: 1.3;
		b {
			font-size: 12.5px;
			font-weight: 550;
			color: var(--dv-text);
			white-space: nowrap;
			overflow: hidden;
			text-overflow: ellipsis;
		}
		small {
			font-size: 11.5px;
			color: var(--dv-text-secondary);
			white-space: nowrap;
			overflow: hidden;
			text-overflow: ellipsis;
		}
	}
	&-more {
		width: var(--dv-control-height);
		height: var(--dv-control-height);
		flex: none;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		border: 0;
		border-radius: var(--dv-radius);
		background: transparent;
		color: var(--dv-text-secondary);
		cursor: pointer;
		&:hover {
			background: var(--dv-hover);
			color: var(--dv-text);
		}
	}
}
</style>
