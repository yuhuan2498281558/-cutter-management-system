import * as api from './api';
import {
    dict,
    UserPageQuery,
    AddReq,
    DelReq,
    EditReq,
    compute,
    CreateCrudOptionsProps,
    CreateCrudOptionsRet
} from '@fast-crud/fast-crud';
import {successMessage} from '/@/utils/message';
import {auth} from '/@/utils/authFunction';
import {commonCrudConfig} from "/@/utils/commonCrud";

export const createCrudOptions = function ({crudExpose}: CreateCrudOptionsProps): CreateCrudOptionsRet {
    const pageRequest = async (query: UserPageQuery) => {
        return await api.getRealtimeParamsList(query);
    };
    const editRequest = async ({form, row}: EditReq) => {
        form.param_id = row.param_id;
        return await api.updateRealtimeParams(form);
    };
    const delRequest = async ({row}: DelReq) => {
        return await api.deleteRealtimeParams(row.param_id);
    };
    const addRequest = async ({form}: AddReq) => {
        return await api.addRealtimeParams(form);
    };

    return {
        crudOptions: {
            table: {
                remove: {
                    confirmMessage: '是否删除该参数？',
                },
            },
            request: {
                pageRequest,
                addRequest,
                editRequest,
                delRequest,
            },
            rowHandle: {
                fixed: 'right',
                width: 200,
                buttons: {
                    edit: {
                        iconRight: 'Edit',
                        type: 'text',
                        show: auth('realtime-params:edit'),
                    },
                    remove: {
                        iconRight: 'Delete',
                        type: 'text',
                        show: auth('realtime-params:delete'),
                    },
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
                param_id: {
                    title: '参数ID',
                    form: {show: false}, // 主键不显示在表单中
                    column: {width: 120},
                },
                thrust: {
                    title: '主机推力',
                    type: 'number',
                    form: {
                        rules: [{required: true, message: '请输入主机推力'}],
                    },
                },
                push_speed: {
                    title: '主机推速',
                    type: 'number',
                    form: {
                        rules: [{required: true, message: '请输入主机推速'}],
                    },
                },
                torque: {
                    title: '主机扭矩',
                    type: 'number',
                    form: {
                        rules: [{required: true, message: '请输入主机扭矩'}],
                    },
                },
                rotation_speed: {
                    title: '主机转速',
                    type: 'number',
                    form: {
                        rules: [{required: true, message: '请输入主机转速'}],
                    },
                },
                cutterhead_pressure: {
                    title: '刀盘压力',
                    type: 'number',
                    form: {
                        rules: [{required: true, message: '请输入刀盘压力'}],
                    },
                },
                cutterhead_speed: {
                    title: '刀盘转速',
                    type: 'number',
                    form: {
                        rules: [{required: true, message: '请输入刀盘转速'}],
                    },
                },
                create_time: {
                    title: '创建时间',
                    type: 'datetime',
                    form: {show: false},
                    column: {width: 180},
                },
                update_time: {
                    title: '更新时间',
                    type: 'datetime',
                    form: {show: false},
                    column: {width: 180},
                },
                ...commonCrudConfig({
                    create_datetime: {
                        form: false,
                        table: true,
                        search: false,
                    },
                    update_datetime: {
                        form: false,
                        table: true,
                        search: false,
                    },
                    creator_name: {
                        form: false,
                        table: true,
                        search: false,
                    },
                    modifier_name: {
                        form: false,
                        table: true,
                        search: false,
                    },
                    dept_belong_id: {
                        form: true,
                        table: true,
                        search: false,
                    },
                    description: {
                        form: true,
                        table: false,
                        search: false,
                    },
                })
            },
        },
    };
};