import * as api from './api';
import { AddReq, DelReq, EditReq, UserPageQuery, UserPageRes } from '@fast-crud/fast-crud';
import { ref } from 'vue';
import { ElMessage } from 'element-plus';

let lastInputValues = {
  shield_model_id: '',
  shield_model: '',
};

export const createCrudOptions = function ({ crudExpose }: { crudExpose: any }) {

  const getLastRecord = async () => {
    try {
      const res = await api.GetList({ page: 1, limit: 1, sort: [{ prop: 'id', order: 'descending' }] });
      if (res.data && res.data.length > 0) {
        const lastRecord = res.data[0];
        lastInputValues.shield_model_id = lastRecord.shield_model_id || '';
        lastInputValues.shield_model = lastRecord.shield_model || '';
      }
    } catch {
      // 非关键操作，静默失败
    }
  };

  getLastRecord();

  // 刀位信息弹窗状态
  const cutterPositionDialogVisible = ref(false);
  const currentShieldMachine = ref<any>(null);

  // 打开刀位信息弹窗
  const openCutterPositionDialog = (row: any) => {
    currentShieldMachine.value = row;
    cutterPositionDialogVisible.value = true;
  };

  return {
    crudOptions: {
      request: {
        pageRequest: async (query: UserPageQuery): Promise<UserPageRes> => await api.GetList(query),
        addRequest: async (req: { form: AddReq }) => {
          lastInputValues.shield_model_id = req.form.shield_model_id;
          lastInputValues.shield_model = req.form.shield_model;
          return await api.AddObj(req.form);
        },
        editRequest: async (req: { form: EditReq }) => await api.UpdateObj(req.form),
        delRequest: async (req: { row: DelReq }) => await api.DelObj(req.row.id),
      },
      form: {
        wrapper: {
          onOpened: ({ mode, form }: any) => {
            if (mode === 'add' && lastInputValues.shield_model_id) {
              setTimeout(() => {
                form.shield_model_id = lastInputValues.shield_model_id;
                form.shield_model = lastInputValues.shield_model;
              }, 100);
            }
          },
        },
      },
      actionbar: {
        buttons: {
          add: {
            show: true,
            text: '新增',
            type: 'primary',
          },
        },
      },
      rowHandle: {
        fixed: 'right',
        width: 280,
        buttons: {
          view: {
            show: false
          },
          edit: {
            show: true,
            text: '编辑',
            iconRight: 'Edit',
            type: 'primary',
            link: true,
          },
          remove: {
            show: true,
            text: '删除',
            iconRight: 'Delete',
            type: 'danger',
            link: true,
          },
          cutterPosition: {
            text: '刀位信息',
            type: 'success',
            link: true,
            iconRight: 'List',
            click: ({ row }: any) => {
              openCutterPositionDialog(row);
            },
          },
        },
      },
      columns: {
        id: {
          title: 'ID',
          type: 'number',
          form: { show: false },
          column: { width: 80 },
        },
        shield_model_id: {
          title: '盾构机模型编号',
          type: 'input',
          form: {
            rules: [{ required: true, message: '请输入盾构机模型编号' }],
          },
        },
        shield_model: {
          title: '盾构机型号',
          type: 'input',
          form: {
            rules: [{ required: true, message: '请输入盾构机型号' }],
          },
        },
        create_datetime: {
          title: '创建时间',
          type: 'datetime',
          form: { show: false },
          column: { width: 160 },
        },
      },
    },
    cutterPositionDialogVisible,
    currentShieldMachine,
  };
};
