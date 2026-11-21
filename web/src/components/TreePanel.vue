<template>
	<section class="tree-panel">
		<el-input v-model="keyword" :prefix-icon="Search" :placeholder="placeholder" clearable class="tree-panel__search" />
		<div v-if="title" class="tree-panel__head">
			<el-icon v-if="icon" class="tree-panel__icon"><component :is="icon" /></el-icon>
			<span class="tree-panel__title">{{ title }}</span>
			<InfoTip v-if="tip" :content="tip" />
			<span v-if="$slots.actions" class="tree-panel__actions"><slot name="actions" /></span>
		</div>
		<div class="tree-panel__body">
			<el-tree ref="treeRef" v-bind="$attrs" :indent="INDENT" highlight-current>
				<template #default="{ node, data }">
					<ElementTreeLine :node="node" :showLabelLine="false" :indent="INDENT">
						<span class="tree-panel__label">
							<slot name="node" :node="node" :data="data">{{ node.label }}</slot>
						</span>
					</ElementTreeLine>
				</template>
			</el-tree>
		</div>
		<div v-if="$slots.footer" class="tree-panel__footer"><slot name="footer" /></div>
	</section>
</template>

<script lang="ts">
// 树的数据、懒加载、过滤方法、点击事件等都按 el-tree 的写法直接写在 <TreePanel> 上，原样转给里面的 el-tree
export default { inheritAttrs: false };
</script>

<script lang="ts" setup>
// 左树右表页面共用的左侧树面板：搜索框 → 标题行（图标、标题、ⓘ、右侧操作）→ 树 → 底部操作栏
import { ref, watch, h } from 'vue';
import type { Component } from 'vue';
import { ElTree } from 'element-plus';
import { Search } from '@element-plus/icons-vue';
import { getElementLabelLine } from 'element-tree-line';
import InfoTip from './InfoTip.vue';

defineProps<{
	placeholder?: string;
	title?: string;
	icon?: Component;
	tip?: string;
}>();

// 缩进与连线间距相同，样式里展开框的位置按这个值算（见 .tree-panel__body）
const INDENT = 16;
const ElementTreeLine = getElementLabelLine(h);
const keyword = ref('');
const treeRef = ref<InstanceType<typeof ElTree>>();

watch(keyword, (val) => {
	treeRef.value?.filter(val);
});

defineExpose({ treeRef });
</script>

<style lang="scss" scoped>
.tree-panel {
	display: flex;
	flex-direction: column;
	gap: 10px;
	height: 100%;
	min-height: 0;
	margin-right: 16px;
	padding-right: 16px;
	border-right: 1px solid var(--dv-divider);
	box-sizing: border-box;
}

.tree-panel__search {
	flex: none;
}

.tree-panel__head {
	display: flex;
	flex: none;
	align-items: center;
	gap: 6px;
	min-height: 24px;
	color: var(--dv-text-regular);
	font-weight: 600;
}

.tree-panel__icon {
	color: var(--dv-text-secondary);
	font-size: 16px;
}

.tree-panel__actions {
	display: flex;
	align-items: center;
	gap: 2px;
	margin-left: auto;
}

.tree-panel__footer {
	display: flex;
	flex: none;
	align-items: center;
	justify-content: space-around;
	height: 40px;
	border-top: 1px solid var(--dv-border);
}

// 标题行右侧和底部操作栏里的图标按钮
.tree-panel__actions,
.tree-panel__footer {
	:deep(.el-icon) {
		width: 28px;
		height: 28px;
		border-radius: var(--dv-radius-sm);
		color: var(--dv-text-secondary);
		cursor: pointer;
	}

	:deep(.el-icon:hover) {
		background-color: var(--dv-hover);
		color: var(--dv-accent-strong);
	}
}

.tree-panel__body {
	flex: 1;
	min-height: 0;
	overflow: auto;

	:deep(.el-tree) {
		--el-tree-node-content-height: 30px;
		--el-tree-node-hover-bg-color: var(--dv-hover);
		--el-tree-text-color: var(--dv-text-regular);
		background: transparent;
		font-size: var(--dv-font-size);
	}

	:deep(.el-tree-node__content) {
		border-radius: var(--dv-radius-sm);
	}

	:deep(.el-tree--highlight-current .el-tree-node.is-current > .el-tree-node__content) {
		background-color: var(--dv-accent-soft);
	}

	// 展开框：16px 宽的位置里画 13px 的加减号方框，不旋转；叶子节点留同样宽的空位
	:deep(.el-tree-node__content > .el-tree-node__expand-icon) {
		justify-content: flex-start;
		width: 16px;
		height: 16px;
		padding: 0;
		transform: none;

		svg {
			display: none;
		}

		&::before {
			content: '';
			width: 13px;
			height: 13px;
			margin-left: 2px;
			border: 1px solid var(--dv-text-muted);
			border-radius: 3px;
			box-sizing: border-box;
			background:
				linear-gradient(var(--dv-text-secondary), var(--dv-text-secondary)) center / 7px 1px no-repeat,
				linear-gradient(var(--dv-text-secondary), var(--dv-text-secondary)) center / 1px 7px no-repeat;
		}

		&.expanded::before {
			background: linear-gradient(var(--dv-text-secondary), var(--dv-text-secondary)) center / 7px 1px no-repeat;
		}
	}

	// 连线（element-tree-line）：竖线对准上一级方框的中线，横线接到本级方框或文字；第一级不画
	:deep(.element-tree-node-line-ver),
	:deep(.element-tree-node-line-hor) {
		margin-left: -8px;
		border-color: var(--dv-border-strong);
	}

	:deep(.element-tree-node-line-ver[style*='left: 0px']),
	:deep(.element-tree-node-line-hor[style*='left: 0px']) {
		display: none;
	}
}

.tree-panel__label {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding-left: 4px;
	white-space: nowrap;
}

// 窄屏时左右两栏上下排列（各页面的 el-col 在 xs 下占满一行），面板改到表格上方
@media (max-width: 767px) {
	.tree-panel {
		height: auto;
		max-height: 360px;
		margin: 0 0 16px;
		padding: 0 0 12px;
		border-right: 0;
		border-bottom: 1px solid var(--dv-divider);
	}
}
</style>
