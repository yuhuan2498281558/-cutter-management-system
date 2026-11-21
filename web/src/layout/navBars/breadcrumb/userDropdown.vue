<template>
	<el-dropdown @command="onHandleCommandClick">
		<slot />
		<template #dropdown>
			<el-dropdown-menu>
				<el-dropdown-item command="/home">{{ $t('message.user.dropdown1') }}</el-dropdown-item>
				<el-dropdown-item command="/personal">{{ $t('message.user.dropdown2') }}</el-dropdown-item>
				<el-dropdown-item divided command="logOut">{{ $t('message.user.dropdown5') }}</el-dropdown-item>
			</el-dropdown-menu>
		</template>
	</el-dropdown>
</template>

<script setup lang="ts" name="layoutBreadcrumbUserDropdown">
import { useRouter } from 'vue-router';
import { ElMessageBox } from 'element-plus';
import { useI18n } from 'vue-i18n';
import { Session } from '/@/utils/storage';

// 用户下拉菜单：顶栏用户名（经典、横向、分栏布局）和侧栏底部的"更多"按钮（侧边栏布局）共用。
// 触发元素由插槽传入，trigger、延时等属性透传给 el-dropdown

// 定义变量内容
const { t } = useI18n();
const router = useRouter();

// 下拉菜单点击时
const onHandleCommandClick = (path: string) => {
	if (path === 'logOut') {
		ElMessageBox({
			closeOnClickModal: false,
			closeOnPressEscape: false,
			title: t('message.user.logOutTitle'),
			message: t('message.user.logOutMessage'),
			showCancelButton: true,
			confirmButtonText: t('message.user.logOutConfirm'),
			cancelButtonText: t('message.user.logOutCancel'),
			buttonSize: 'default',
			beforeClose: (action, instance, done) => {
				if (action === 'confirm') {
					instance.confirmButtonLoading = true;
					instance.confirmButtonText = t('message.user.logOutExit');
					setTimeout(() => {
						done();
						setTimeout(() => {
							instance.confirmButtonLoading = false;
						}, 300);
					}, 700);
				} else {
					done();
				}
			},
		})
			.then(async () => {
				// 清除缓存/token等
				Session.clear();
				// 使用 reload 时，不需要调用 resetRoute() 重置路由
				window.location.reload();
			})
			.catch(() => {});
	} else {
		router.push(path);
	}
};
</script>
