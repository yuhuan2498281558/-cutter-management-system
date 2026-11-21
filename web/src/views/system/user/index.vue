<template>
  <fs-page>
    <el-row class="user-el-row">
      <el-col :xs="24" :sm="8" :md="7" :lg="6" :xl="5" class="user-side">
        <TreePanel placeholder="请输入部门名称" title="部门列表" :icon="HomeFilled" :tip="content" :props="treeProps"
                   lazy :load="loadNode" :filter-node-method="filterNode" @node-click="onTreeNodeClick">
          <template #node="{ node, data }">
            <SvgIcon name="iconfont icon-shouye" :color="data.status ? 'var(--el-color-primary)' : undefined"/>
            <span>{{ node.label }}</span>
          </template>
        </TreePanel>
      </el-col>
      <el-col :xs="24" :sm="16" :md="17" :lg="18" :xl="19" class="user-main">
        <fs-crud ref="crudRef" v-bind="crudBinding">
          <template #actionbar-right>
            <importExcel api="api/system/user/">导入</importExcel>
          </template>
        </fs-crud>
      </el-col>
    </el-row>

  </fs-page>
</template>

<script lang="ts" setup name="user">
import {useExpose, useCrud} from '@fast-crud/fast-crud';
import {createCrudOptions} from './crud';
import * as api from './api';
import {ref, onMounted, toRaw} from 'vue';
import {HomeFilled} from '@element-plus/icons-vue';
import type Node from 'element-plus/es/components/tree/src/model/node';
import TreePanel from '/@/components/TreePanel.vue';
import importExcel from '/@/components/importExcel/index.vue';


interface Tree {
  id: number;
  name: string;
  status: boolean;
  hasChild: boolean;
}

interface APIResponseData {
  code?: number;
  data: Tree[];
  msg?: string;
}

const treeProps = {
  label: 'name',
  isLeaf: (data: Tree) => !data.hasChild,
};

// 搜索只在已经展开加载过的部门里找
const filterNode = (value: string, data: Tree) => {
  if (!value) return true;
  return toRaw(data).name.indexOf(value) !== -1;
};

const content = `
1.部门信息;
`;

// 部门树懒加载：先取顶级部门，展开哪个部门再取它的下级
const loadNode = (node: Node, resolve: (data: Tree[]) => void) => {
  const query = node.level === 0 ? {} : {parent: node.data.id};
  api.GetDept(query).then((ret: APIResponseData) => resolve(ret.data))
    .catch(() => resolve([]));
};

//树形点击事件
const onTreeNodeClick = (node: any) => {
  const {id} = node;
  crudExpose.doSearch({form: {dept: id}});
};

// crud组件的ref
const crudRef = ref();
// crud 配置的ref
const crudBinding = ref();
// 暴露的方法
const {crudExpose} = useExpose({crudRef, crudBinding});
// 你的crud配置
const {crudOptions} = createCrudOptions({crudExpose});
// 初始化crud配置
const {resetCrudOptions} = useCrud({crudExpose, crudOptions});

// 页面打开后获取列表数据
onMounted(() => {
  crudExpose.doRefresh();
});
</script>

<style lang="scss" scoped>
.user-el-row {
  height: 100%;
  overflow: hidden;

  .el-col {
    height: 100%;
    padding: 10px 0;
    box-sizing: border-box;
  }
}

// 窄屏时部门树在上、表格在下：树按内容撑开，表格仍占满一屏，整体滚动
@media (max-width: 767px) {
  .user-el-row {
    overflow-y: auto;

    .user-side {
      height: auto;
    }
  }
}
</style>
