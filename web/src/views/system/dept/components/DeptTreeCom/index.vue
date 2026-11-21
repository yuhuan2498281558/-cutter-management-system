<template>
	<TreePanel
		ref="panelRef"
		placeholder="请输入部门名称"
		title="部门架构"
		:icon="HomeFilled"
		:data="treeData"
		:props="defaultTreeProps"
		:filter-node-method="handleFilterTreeNode"
		:load="handleLoadNode"
		lazy
		@node-click="handleNodeClick"
	>
		<template #actions>
			<el-icon size="16" @click="() => (showTotalNum = !showTotalNum)">
				<View v-show="!showTotalNum" />
				<Hide v-show="showTotalNum" />
			</el-icon>
		</template>

		<template #node="{ node, data }">
			<SvgIcon name="iconfont icon-shouye" :color="data.status ? 'var(--el-color-primary)' : undefined" />
			<span>
				{{ node.label }}<span v-if="data.status" v-show="showTotalNum">（{{ data.dept_user_count }}人）</span>
			</span>
		</template>

		<template #footer>
			<el-tooltip effect="dark" content="新增">
				<el-icon size="16" @click="handleUpdateMenu('create')">
					<Plus />
				</el-icon>
			</el-tooltip>

			<el-tooltip effect="dark" content="编辑">
				<el-icon size="16" @click="handleUpdateMenu('update')">
					<Edit />
				</el-icon>
			</el-tooltip>

			<el-tooltip effect="dark" content="上移">
				<el-icon size="16" @click="handleSort('up')">
					<Top />
				</el-icon>
			</el-tooltip>

			<el-tooltip effect="dark" content="下移">
				<el-icon size="16" @click="handleSort('down')">
					<Bottom />
				</el-icon>
			</el-tooltip>

			<el-tooltip effect="dark" content="删除">
				<el-icon size="16" @click="handleDeleteDept">
					<Delete />
				</el-icon>
			</el-tooltip>
		</template>
	</TreePanel>
</template>

<script lang="ts" setup>
import { ref, computed, toRaw } from 'vue';
import { HomeFilled, View, Hide, Plus, Edit, Top, Bottom, Delete } from '@element-plus/icons-vue';
import TreePanel from '/@/components/TreePanel.vue';
import { lazyLoadDept, deptMoveUp, deptMoveDown } from '../../api';
import { warningNotification } from '/@/utils/message';
import { TreeItemType, APIResponseData } from '../../types';
import type Node from 'element-plus/es/components/tree/src/model/node';

interface IProps {
	treeData: TreeItemType[];
}

const defaultTreeProps: any = {
	children: 'children',
	label: 'name',
	isLeaf: (data: TreeItemType[], node: Node) => {
		if (node.data.hasChild) {
			return false;
		} else {
			return true;
		}
	},
};

withDefaults(defineProps<IProps>(), {
	treeData: () => [],
});
const emit = defineEmits(['treeClick', 'deleteDept', 'updateDept']);

let showTotalNum = ref(false);
let sortDisable = ref(false);
let treeSelectDept = ref<TreeItemType>({});
let treeSelectNode = ref<Node | null>(null);
const panelRef = ref<InstanceType<typeof TreePanel>>();
// 父页面通过 treeRef 读取当前选中节点（编辑时取上级部门）
const treeRef = computed(() => panelRef.value?.treeRef);

/**
 * 部门树的搜索事件
 */
const handleFilterTreeNode = (value: string, data: TreeItemType) => {
	if (!value) return true;
	return toRaw(data).name?.indexOf(value) !== -1;
};

/**
 * 部门树的懒加载
 */
const handleLoadNode = (node: Node, resolve: Function) => {
	if (node.level !== 0) {
		lazyLoadDept({ parent: node.data.id }).then((res: APIResponseData) => {
			resolve(res.data);
		});
	}
};

/**
 * 部门的点击事件
 */
const handleNodeClick = (record: TreeItemType, node: Node) => {
	treeSelectDept.value = record;
	treeSelectNode.value = node;
	emit('treeClick', record);
};

/**
 * 新增 or 编辑 操作
 */
const handleUpdateMenu = (type: string) => {
	if (type === 'update') {
		if (!treeSelectDept.value.id) {
			warningNotification('请选择菜单！');
			return;
		}
		emit('updateDept', type, treeSelectDept.value);
	} else {
		emit('updateDept', type);
	}
};

/**
 * 删除部门
 */
const handleDeleteDept = () => {
	if (!treeSelectDept.value.id) {
		warningNotification('请选择菜单！');
		return;
	}
	emit('deleteDept', treeSelectDept.value.id, () => {
		treeSelectDept.value = {};
	});
};

/**
 * 部门上下移动操作
 */
const handleSort = async (type: string) => {
	if (!treeSelectDept.value.id) {
		warningNotification('请选择菜单！');
		return;
	}
	if (sortDisable.value) return;

	const parentList = treeSelectNode.value?.parent.childNodes || [];
	const index = parentList.findIndex((i) => i.data.id === treeSelectDept.value.id);
	const record = parentList.find((i) => i.data.id === treeSelectDept.value.id);

	if (type === 'up') {
		if (index === 0) return;
		parentList.splice(index - 1, 0, record as any);
		parentList.splice(index + 1, 1);
		sortDisable.value = true;
		await deptMoveUp({ dept_id: treeSelectDept.value.id });
		sortDisable.value = false;
	}
	if (type === 'down') {
		parentList.splice(index + 2, 0, record as any);
		parentList.splice(index, 1);
		sortDisable.value = true;
		await deptMoveDown({ dept_id: treeSelectDept.value.id });
		sortDisable.value = false;
	}
};

defineExpose({
	treeRef,
});
</script>
