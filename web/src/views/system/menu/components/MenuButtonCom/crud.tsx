import {AddReq, DelReq, EditReq, dict, CreateCrudOptionsRet, CreateCrudOptionsProps} from '@fast-crud/fast-crud';
import * as api from './api';
import {auth} from '/@/utils/authFunction'
import {request} from '/@/utils/service';
import { successNotification } from '/@/utils/message';
import { ElMessage } from 'element-plus';



// 注释编号:django-vue3-admin-crud035117:代码开始行
// 功能说明:自定义表单From，做一键添加添加权限的功能

let selectedId:any = null   // 注释编号:django-vue3-admin-crud285811:定义selectedId来保存当前选中的菜单ID


// 注释编号:django-vue3-admin-crud075911:重新定义一条新增对象的函数
const addImportRequest = async (form: AddReq) => {
    return await api.AddObj(form);
};


import {
    CrudExpose,
    CrudOptions,
    useColumns,
    useFormWrapper,
  } from "@fast-crud/fast-crud";


function useCustomFormWrapperDemo(crudExpose: CrudExpose) {
    // 自定义表单配置
    const { buildFormOptions } = useColumns();
    const customOptions: CrudOptions = {


     //在这里自定义表单的字段
      columns: {
        keywords: {
          title: "输入权限关键字符",
          type: "text",
          form: {
            rules: [{required: true, message: '关键字符必填'}],
          },
        },
      },
      form: {
        wrapper: {
            // 传入form页面的title名称
          title: "一键添加通用权限",
        },

        //  注释编号:django-vue3-admin-crud155411:代码开始行
        //  功能说明:这里写标准化的按钮权限数据
        async doSubmit({ form }) {
            // 检查 keywords 和 selectedId 的有效性
            if (!form.keywords || !selectedId) {
                console.error("Invalid keywords or selectedId.");
                return false;
            }

            const keywords = form.keywords; //拿到当前关键字
            const baseApiPath = "/api/";

            // 定义操作类型及其对应的method, 如下其中method方法的为对应是get:0、post:1、put:2、DELETE:3
            const operations = [
                { name: "删除", action: "Delete", method: 3, suffix: "/{id}/" },
                { name: "复制", action: "Copy", method: 0, suffix: "" },
                { name: "导入", action: "Import", method: 1, suffix: "/import_data/" },
                { name: "导出", action: "Export", method: 1, suffix: "/export_data/" },
                { name: "新增", action: "Create", method: 1, suffix: "" },
                { name: "查询", action: "Search", method: 0, suffix: "" },
                { name: "编辑", action: "Update", method: 2, suffix: "/{id}/" },
                { name: "详情", action: "Retrieve", method: 0, suffix: "/{id}/" },
            ];

            try {
                // 使用 Promise.all 并行处理请求
                const promises = operations.map(async ({ name, action, method, suffix }) => {
                    const value = `${keywords}:${action}`;
                    const api = `${baseApiPath}${keywords}${suffix}`;
                    const obj = { value, name, method, api, menu: selectedId };
                    await addImportRequest(obj);
                });

                await Promise.all(promises);

                crudExpose.doRefresh();   // 一定要刷新当前页面
            } catch (error) {
                console.error("Failed to submit requests:", error);
                return false;  // 错误时返回false，可以根据实际需要调整
            }


            return true;    // 无论如何都要关闭当前窗口
        }
        //  注释编号:django-vue3-admin-crud155411:代码结束行



      }
    };

    const { openDialog } = useFormWrapper();
    //使用crudOptions结构来构建自定义表单配置
    //打开自定义表单
    const openCustomForm = async () => {
      const formOptions = buildFormOptions(customOptions);
      const dialogRef = await openDialog(formOptions);

    };

    return {
      openCustomForm,
    };
  }

// 注释编号:django-vue3-admin-crud035117:代码结束行



//此处为crudOptions配置
export const createCrudOptions = function ({crudExpose, context}: CreateCrudOptionsProps): CreateCrudOptionsRet {

    const { openCustomForm } = useCustomFormWrapperDemo(crudExpose);  // 注释编号:django-vue3-admin-crud260010:定义自定义表单

    const pageRequest = async () => {
        if (context!.selectOptions.value.id){

            selectedId = context!.selectOptions.value.id;  // 注释编号:django-vue3-admin-crud545209:把当前选中的菜单id赋值给selectedId

            return await api.GetList({menu: context!.selectOptions.value.id} as any);
        } else {
            return undefined;
        }
    };
    const editRequest = async ({form, row}: EditReq) => {
        return await api.UpdateObj({...form, menu: row.menu});
    };
    const delRequest = async ({row}: DelReq) => {
        return await api.DelObj(row.id);
    };
    const addRequest = async ({form}: AddReq) => {
        return await api.AddObj({...form, ...{menu: context!.selectOptions.value.id}});
    };
    return {
        crudOptions: {
            pagination:{
                show:false
            },
            search: {
                container: {
                    action: {
                        //按钮栏配置
                        col: {
                            span: 8,
                        },
                    },
                },
            },
            actionbar: {
                buttons: {
                    add: {
                        show: auth('btn:Create')
                    },
                    batchAdd: {
						show: true,
						type: 'primary',
						text: '批量生成',
						click: async () => {
							if (context!.selectOptions.value.id == undefined) {
								ElMessage.error('请选择菜单');
								return;
							}
							const result = await api.BatchAdd({ menu: context!.selectOptions.value.id });
							if (result.code == 2000) {
								successNotification(result.msg);
								crudExpose.doRefresh();
							}
						},
					},
                    // 注释编号:django-vue3-admin-crud401314:代码开始行
                    // 功能说明:添加一键添加通用权限按钮
                    addImport:{
                        text: '一键添加通用权限',	//按钮显示名称
                        type: "success",
                        async click() {
                            await openCustomForm();
                        },
                        show: auth('btn:addImport')
                    },
                    // 注释编号:django-vue3-admin-crud401314:代码结束行

                    export:{
                        show: false    //因为在setting中配置了默认show，所以这里需要配置成隐藏
                    }

                },
            },
            rowHandle: {
                //固定右侧
                fixed: 'right',
                width: 200,
                buttons: {
					view: {
						type: 'text',
						show: true,
						style:{color: "#67C23A"},
						order: 1,
					},
                    edit: {
						icon: '',
						type: 'text',
						style:{color: "#E6A23C"},
						order: 2,
						show: auth('btn:Update')
                    },
                    copy: {
						text: '复制',	//按钮显示名称
						type: 'text',	//按钮类型
						order: 3,		//排序，这个看自己喜欢排在什么位置了
						style:{color: "#606266"},
						title: '复制',
						click: (context: any): void => {
							// 这里必须拿到了context里面的row属性并且赋值给newrow，接下来做一个深拷贝出来一个全新与源对象无关系的对象row
							let newrow = context.row;
							let row = JSON.parse(JSON.stringify(newrow));
							//  官方调用openAdd: (context: OpenEditContext, formOpts?: OpenDialogProps) => Promise<any>;其中formOpts就是指form的选择配置
							//	第一个参数只能传命名为row的参数，别的名称好像不行。
							// 第二个参数是传了form的title名称进去{wrapper:{title:"复制数据"}}，如果要传其它参数，可根据情况而定
							crudExpose.openAdd({row},{wrapper:{title:"复制数据"}})

						},
                        show: auth('btn:Copy')
					},
                    remove: {
                        show: auth('btn:Delete')
                    },
                },
            },
            request: {
                pageRequest,
                addRequest,
                editRequest,
                delRequest,
            },
            form: {
                col: {span: 24},
                labelWidth: '100px',
                wrapper: {
                    is: 'el-dialog',
                    width: '600px',
                },
            },
            columns: {
                _index: {
                    title: '序号',
                    form: {show: false},
                    column: {
                        type: 'index',
                        align: 'center',
                        width: '70px',
                    },
                },
                search: {
                    title: '关键词',
                    column: {show: false},
                    type: 'text',
                    search: {show: true},
                    form: {
                        show: false,
                        component: {
                            placeholder: '输入关键词搜索',
                        },
                    },
                },
                id: {
                    title: 'ID',
                    type: 'text',
                    column: {show: false},
                    search: {show: false},
                    form: {show: false},
                },
                name: {
                    title: '权限名称',
                    type: 'text',
                    search: {show: true},
                    column: {
                        minWidth: 120,
                        sortable: true,
                    },
                    form: {
                        rules: [{required: true, message: '权限名称必填'}],
                        component: {
                            placeholder: '输入权限名称搜索',
                            props: {
                                clearable: true,
                                allowCreate: true,
                                filterable: true,
                            },
                        },
                        helper: {
                            render() {
                                return <el-alert title="手动输入" type="warning"
                                                 description="页面中按钮的名称或者自定义一个名称"/>;
                            },
                        },
                    },
                },
                value: {
                    title: '权限值',
                    type: 'text',
                    search: {show: false},
                    column: {
                        width: 200,
                        sortable: true,
                    },
                    form: {
                        rules: [{required: true, message: '权限标识必填'}],
                        placeholder: '输入权限标识',
                        helper: {
                            render() {
                                return <el-alert title="唯一值" type="warning"
                                                 description="用于判断前端按钮权限或接口权限"/>;
                            },
                        },
                    },
                },
                method: {
                    title: '请求方式',
                    search: {show: false},
                    type: 'dict-select',
                    column: {
                        width: 120,
                        sortable: true,
                    },
                    dict: dict({
                        data: [
                            {label: 'GET', value: 0},
                            {label: 'POST', value: 1, color: 'success'},
                            {label: 'PUT', value: 2, color: 'warning'},
                            {label: 'DELETE', value: 3, color: 'danger'},
                        ],
                    }),
                    form: {
                        rules: [{required: true, message: '必填项'}],
                    },
                },
                api: {
                    title: '接口地址',
                    search: {show: false},
                    type: 'dict-select',
                    dict: dict({
                        getData() {
                            return request({url: '/swagger.json'}).then((res: any) => {
                                const ret = Object.keys(res.paths);
                                const data = [];
                                for (const item of ret) {
                                    const obj: any = {};
                                    obj.label = item;
                                    obj.value = item;
                                    data.push(obj);
                                }
                                return data;
                            });
                        },
                    }),
                    column: {
                        minWidth: 250,
                        sortable: true,
                    },
                    form: {
                        rules: [{required: true, message: '必填项'}],
                        component: {
                            props: {
                                allowCreate: true,
                                filterable: true,
                                clearable: true,
                            },
                        },
                        helper: {
                            render() {
                                return <el-alert title="请正确填写，以免请求时被拦截。匹配单例使用正则,例如:/api/xx/.*?/"
                                                 type="warning"/>;
                            },
                        },
                    },
                },
            },
        },
    };
};
