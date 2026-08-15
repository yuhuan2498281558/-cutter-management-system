<template>
  <div class="tool-archive-container">
    <!-- 搜索表单 -->
    <el-form
      :model="searchForm"
      ref="formRef"
      inline
      label-width="80px"
      class="mb-4"
    >
    <el-form-item label="刀具ID">
        <el-input
          v-model="searchForm.tool_id"
          placeholder="请输入刀具ID"
          clearable
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="刀具名称">
        <el-input
          v-model="searchForm.tool_name"
          placeholder="请输入刀具名称"
          clearable
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="刀具类别">
        <el-input
          v-model="searchForm.tool_type"
          placeholder="请输入刀具类别"
          clearable
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="规格型号">
        <el-input
          v-model="searchForm.specification"
          placeholder="请输入规格型号"
          clearable
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="制造商">
        <el-input
          v-model="searchForm.manufacturer"
          placeholder="请输入制造商"
          clearable
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="采购日期">
        <el-date-picker
          v-model="searchForm.purchase_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="请选择采购日期"
          clearable
          @change="handleQuery"
        />
      </el-form-item>
      <el-form-item label="采购价格">
        <el-date-picker
          v-model="searchForm.purchase_price"
          type="number"
          placeholder="请输入采购价格"
          clearable
          @change="handleQuery"
        />
      </el-form-item>
      <el-form-item label="使用寿命">
        <el-input
          v-model="searchForm.service_life"
          placeholder="请输入使用寿命"
          clearable
          @change="handleQuery"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="Search" @click="handleQuery">搜索</el-button>
        <el-button icon="Refresh" @click="handleReset">重置</el-button>
      </el-form-item>
    </el-form>

    <!-- 操作按钮 -->
    <el-row :gutter="10" class="mb-4">
      <el-col :span="1.5">
        <el-button
          type="primary"
          plain
          icon="Plus"
          @click="handleAdd"
          v-hasPermi="['system:toolarchive:add']"
        >新增</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="danger"
          plain
          icon="Delete"
          :disabled="selectedRowKeys.length === 0"
          @click="handleDelete"
          v-hasPermi="['system:toolarchive:delete']"
        >删除</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="warning"
          plain
          icon="Download"
          @click="handleExport"
          v-hasPermi="['system:toolarchive:export']"
        >导出</el-button>
      </el-col>
    </el-row>

    <!-- 数据表格 -->
    <el-table
      v-loading="loading"
      :data="tableData"
      @selection-change="handleSelectionChange"
      border
      style="width: 100%"
    >
      <el-table-column type="selection" width="55" />
      <el-table-column prop="id" label="ID" align="center" />
      <el-table-column prop="tool_id" label="刀具ID" align="center" />
      <el-table-column prop="tool_name" label="刀具名称" align="center" />
      <el-table-column prop="tool_type" label="刀具类别" align="center" />
      <el-table-column prop="specification" label="规格型号" align="center" />
      <el-table-column prop="manufacturer" label="制造商" align="center" />
      <el-table-column prop="purchase_price" label="采购价格" align="center" />
      <el-table-column prop="service_life" label="使用寿命" align="center" />
      <el-table-column prop="purchase_date" label="采购日期" align="center">
        <template #default="scope">
          {{ scope.row.time || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" align="center">
        <template #default="scope">
          <el-button
            link
            type="primary"
            icon="Edit"
            @click="handleEdit(scope.row)"
            v-hasPermi="['system:toolarchive:edit']"
          >修改</el-button>
          <el-button
            link
            type="danger"
            icon="Delete"
            @click="handleRowDelete(scope.row.id)"
            v-hasPermi="['system:toolarchive:delete']"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页组件 -->
    <el-pagination
      v-show="total > 0"
      :total="total"
      v-model:page-size="searchForm.pageSize"
      v-model:current-page="searchForm.pageNum"
			@size-change="handleSizeChange"
      @current-change="handlePageChange"
      layout="total, sizes, prev, pager, next, jumper"
      class="mt-4"
    />

    <!-- 新增/编辑弹窗 -->
    <el-dialog
      :title="dialogTitle"
      v-model="dialogVisible"
      width="600px"
      append-to-body
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="100px"
      >
        <el-form-item label="刀具ID" prop="tool_id">
          <el-input v-model="form.tool_id" placeholder="请输入刀具ID" />
        </el-form-item>
        <el-form-item label="刀具名称" prop="tool_name">
          <el-input v-model="form.tool_name" placeholder="请输入刀具名称" />
        </el-form-item>
        <el-form-item label="刀具类别" prop="tool_type">
          <el-input v-model="form.tool_type" placeholder="请输入刀具类别" />
        </el-form-item>
        <el-form-item label="规格型号" prop="specification">
          <el-input v-model="form.specification" placeholder="请输入规格型号" />
        </el-form-item>
        <el-form-item label="制造商" prop="manufacturer">
          <el-input v-model="form.manufacturer" placeholder="请输入制造商" />
        </el-form-item>
        <el-form-item label="采购价格" prop="purchase_price">
          <el-input v-model="form.purchase_price" placeholder="请输入采购价格" />
        </el-form-item>
        <el-form-item label="使用寿命" prop="service_life">
          <el-input v-model="form.service_life" placeholder="请输入使用寿命" />
        </el-form-item>
        <el-form-item label="采购日期" prop="purchase_date">
          <el-date-picker
            v-model="form.purchase_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="请选择采购日期"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleDialogSubmit">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, unref, reactive, onMounted } from 'vue';
import { ElMessageBox, ElMessage } from 'element-plus';
import { request } from '/@/utils/service';
import { UserPageQuery, AddReq, EditReq } from '@fast-crud/fast-crud';
import { formatDate } from '/@/utils/formatTime';
import  dateFormatYMDHMS  from '/@/utils/commonFunction'
import {
  getToolList,
  addTool,
  deleteTool,
  exportTool,
  updateTool,
} from './api';


const formRef = ref<any>(null);
const handleDialogSubmit =  () => {
   unref(formRef).validate((valid: boolean) => {
  if (valid) {
		if (form.id) {
			updateTool(form).then(() => {
				ElMessage.success('修改成功');
				handleQuery();
				dialogVisible.value = false;
			}).catch(() => {
				ElMessage.error('修改失败');
			})
		} else {
			addTool(form).then(() => {
				ElMessage.success('添加成功');
				handleQuery();
				dialogVisible.value = false;
			}).catch(() => {
				ElMessage.error('添加失败');
			})
		}
    }
   });
};
const ids = ref([]);
const tableData = ref([]);
const total = ref(0);
const loading = ref(true);
const selectedRowKeys = ref<any[]>([]);
const dialogVisible = ref(false);
const dialogTitle = ref('');
const formData = reactive({
  form: {
    id: '', // Added id property
    tool_id: '',
    tool_name: '',
    tool_type: '',
    specification: '',
    manufacturer: '',
    purchase_price: '',
    service_life: '',
    purchase_date: '',
  },
	searchForm: {
    pageNum: 1,
    pageSize: 10,
    tool_id: '',
    tool_name: '',
    tool_type: '',
    specification: '',
    manufacturer: '',
    purchase_price: '',
    service_life: '',
    purchase_date: '',
  },
	formRules:{
    tool_id: [{ required: true, message: '请输入刀具ID', trigger: 'blur' }],
    tool_name: [{ required: true, message: '请输入刀具名称', trigger: 'blur' }],
    tool_type: [{ required: true, message: '请输入刀具类别', trigger: 'blur' }],
    specification: [{ required: true, message: '请输入规格型号', trigger: 'blur' }],
    manufacturer: [{ required: true, message: '请输入制造商', trigger: 'blur' }],
    purchase_price: [{ required: true, message: '请输入采购价格', trigger: 'blur' }],
    service_life: [{ required: true, message: '请输入使用寿命', trigger: 'blur' }],
    purchase_date: [{ required: true, message: '请选择采购日期', trigger: 'change' }],
  },
});

const {form, searchForm, formRules} = formData;
const resetForm = () => {
  form.id = '';
  form.tool_id = '';
  form.tool_name = '';
  form.tool_type = '';
  form.specification = '';
  form.manufacturer = '';
  form.purchase_price = '';
  form.service_life = '';
  form.purchase_date = '';
};

/** 初始化列表 */
onMounted(() => {
  handleQuery();
});

/** 查询列表 */
function handleQuery () {
  loading.value = true;
  getToolList(searchForm)
    .then((res: any) => {
      tableData.value = res.data || [];
      total.value = res.data?.length || 0;
			loading.value = false;
    })
    .catch((err: any) => {
      console.error('查询失败:', err);
			loading.value = false;
    })
    .finally(() => {
      loading.value = false;
    });
};

/** 重置查询 */
const handleReset = () => {
  form.id = ''; // 重置 id

  form.tool_id = '';
  form.tool_name = '';
  form.tool_type = '';
  form.specification = '';
  form.manufacturer = '';
  form.purchase_price = '';
  form.service_life = '';
  form.purchase_date = '';

  handleQuery();
};

/** 分页 - 每页条数改变 */
const handleSizeChange = (val: number) => {
  searchForm.pageSize = val;
  handleQuery();
};

/** 分页 - 当前页改变 */
const handlePageChange = (val: number) => {
  searchForm.pageNum = val;
  handleQuery();
};

/** 多选事件 */
const handleSelectionChange = (val: any[]) => {
  selectedRowKeys.value = val.map((item) => item.id);
};

/** 新增 */
const handleAdd = () => {
  dialogTitle.value = '新增项目';
  resetForm();
  dialogVisible.value = true;
};

/** 修改 */
function handleEdit (row: any) {
  dialogTitle.value = '修改项目';
  resetForm();
	const _id = row.id || ids.value[0]
  form.id = _id;

  Object.assign(form, JSON.parse(JSON.stringify(row)));
  dialogVisible.value = true;
};

/** 删除（单条） */
const handleRowDelete = (id: string | number) => {
  if (!id) {
    console.log('请选择要删除的记录');
    return;
  }
  ElMessageBox.confirm('此操作将永久删除该记录, 是否继续?', '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(() => {
      return deleteTool(id);
    })
    .then(() => {
      ElMessage.success('删除成功!');
      handleQuery();
    })
    .catch(() => {
      ElMessage.info('已取消删除');
    });
};

/** 删除（批量） */
const handleDelete = () => {
  if (selectedRowKeys.value.length === 0) {
    ElMessage.warning('请选择要删除的记录');
    return;
  }
  ElMessageBox.confirm('此操作将永久删除选中记录, 是否继续?', '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(() => {
      return deleteTool(selectedRowKeys.value[0]);
    })
    .then(() => {
      ElMessage.success('删除成功!');
      handleQuery();
    })
    .catch(() => {
      ElMessage.info('已取消删除');
			selectedRowKeys.value = [];
			handleQuery();
		});
};
/** 导出项目信息 */
function handleExport() {
  // 检查是否有数据可导出
  if (tableData.value.length === 0) {
    ElMessage.warning('暂无数据可导出');
    return;
  }
	try {
    // 定义 CSV 表头（根据实际数据字段调整）
    const headers = [
      '刀具ID', '刀具名称', '刀具类别', '规格型号',
      '制造商', '采购价格', '使用寿命', '采购日期'
    ];

    // 定义表头对应的字段名（与表格数据结构匹配）
    const fields = [
      'tool_id', 'tool_name', 'tool_type', 'specification',
      'manufacturer', 'purchase_price', 'service_life', 'purchase_date'
    ];

    // 生成 CSV 表头行
    let csvContent = headers.join(',') + '\n';

    // 生成数据行
    tableData.value.forEach(item => {
      const row = fields.map(field => {
        // 获取字段值，处理空值和特殊字符
        let value = item[field] || '';
        value = String(value).replace(/"/g, '""'); // 处理双引号
        if (value.includes(',') || value.includes('\n') || value.includes('"')) {
          value = `"${value}"`; // 用双引号包裹包含特殊字符的值
        }
        return value;
      });
      csvContent += row.join(',') + '\n';
    });

    // 创建 Blob 对象
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });

    // 创建下载链接
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;

    // 生成带时间戳的文件名
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    link.download = `刀具列表_${timestamp}.csv`;

    // 触发下载
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    ElMessage.success('导出成功');
  } catch (error) {
    console.error('导出失败:', error);
    ElMessage.error('导出失败，请重试');
  }
}

</script>
