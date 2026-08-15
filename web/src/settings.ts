// 引入fast-crud
import { FastCrud, useTypes} from '@fast-crud/fast-crud';
const { getType } = useTypes();
import '@fast-crud/fast-crud/dist/style.css';
import {setLogger} from '@fast-crud/fast-crud';
import {getBaseURL} from '/@/utils/baseUrl';
// element
import ui from '@fast-crud/ui-element';
import {request} from '/@/utils/service';
//扩展包
import {FsExtendsEditor, FsExtendsUploader,FsCropperUploader} from '@fast-crud/fast-extends';
import '@fast-crud/fast-extends/dist/style.css';
import { successNotification } from '/@/utils/message';
import _ from 'lodash-es';
import XEUtils from "xe-utils";

import {auth} from '/@/utils/authFunction'   // 注释编号:django-vue3-admin-settings091316: 导入auth函数


export default {
	// async install(app: any, options: any) {
	async install(app: any) {
		// 先安装ui
		app.use(ui);
		// 然后安装FastCrud
		app.use(FastCrud, {
            //i18n, //i18n配置，可选，默认使用中文，具体用法请看demo里的 src/i18n/index.js 文件
            // 此处配置公共的dictRequest（字典请求）
            async dictRequest({dict}: any) {
                const {isTree} = dict
                //根据dict的url，异步返回一个字典数组
                return await request({url: dict.url, params: dict.params || {}}).then((res: any) => {
                    if (isTree) {
                        return XEUtils.toArrayTree(res.data, {parentKey: 'parent'})
                    }
                    return res.data
                });
            },
			//公共crud配置
			commonOptions(props: any) { // 这里props包了当前index传过来的context
				return {
					request: {
						//接口请求配置
						//你项目后台接口大概率与fast-crud所需要的返回结构不一致，所以需要配置此项
						//请参考文档http://fast-crud.docmirror.cn/api/crud-options/request.html
						transformQuery: ({ page, form, sort }: any) => {
							if (sort.asc !== undefined) {
								form['ordering'] = `${sort.asc ? '' : '-'}${sort.prop}`;
							}
							//转换为你pageRequest所需要的请求参数结构
							return { page: page.currentPage, limit: page.pageSize, ...form };
						},
						transformRes: ({ res }: any) => {
							//将pageRequest的返回数据，转换为fast-crud所需要的格式
							//return {records,currentPage,pageSize,total};
							return { records: res.data, currentPage: res.page, pageSize: res.limit, total: res.total };
						},
					},

					// 注释编号:django-vue3-admin-settings544915:代码开始行
					// 功能说明:注意，这里统一使用props.context.componentName去拿到每个crud对应的index传过来的name名称
					actionbar: {
						buttons: {
							add: {
								show: auth(`${props.context.componentName}:Create`),
							},
							export:{
								text:"导出",//按钮文字
								title:"导出",//鼠标停留显示的信息
								show: auth(`${props.context.componentName}:Export`),
							}
						}
					},
					// 注释编号:django-vue3-admin__settings344115:代码开始行
					// 功能说明:table表页面中右边的查看、编辑、复制、删除四个按钮的样式全局统一
					rowHandle: {

						//固定右侧
						fixed: 'right',
						width: 170,
						buttons: {
							view: {
								type: 'text', //查看按钮
								// show: true,
								show: auth(`${props.context.componentName}:Retrieve`),
								style:{color: "#67C23A"},
								order: 1,
							},
							edit: {
								type: 'text', //编辑按钮
								style:{color: "#E6A23C"},
								order: 2,
								show: auth(`${props.context.componentName}:Update`),
							},
							// 注释编号:django-vue3-admin__settings415814:代码开始行
							// 功能说明:这里是复制按钮的集中配置
							copy: {
								text: '复制',	//按钮显示名称
								type: 'text',	//按钮类型
								order: 3,		//排序，这个看自己喜欢排在什么位置了
								style:{color: "#606266"},
								title: '复制',
								click: (context: any): void => {
									// 这里必须拿到了context里面的row属性并且赋值给newrow，接下来做一个深拷贝出来一个全新与源对象无关系的对象row
									const row = context.row
									row.id = null   //复制时，要把id给过滤掉，其它的值就可以不需要理会了。
									props.crudExpose.openAdd({row},{wrapper:{title:"复制数据"}})  //这个props是由前面commonOptions(props: any)传进来的
								// }
							},
								show: auth(`${props.context.componentName}:Copy`),
							},
							// 注释编号:django-vue3-admin__settings415814:代码结束行
							remove: {
								type: 'text', //删除按钮
								style:{color: "#F56C6C"},
								order: 4,
								show: auth(`${props.context.componentName}:Delete`),
							},

						},

						// 注释编号:django-vue3-admin-settings324009:代码开始行


						// 注释编号:django-vue3-admin-settings544915:代码结束行



						// 功能说明:子表行编辑情况下，按钮的样式定制
						group:{
							editRow: {

								edit: { //行编辑模式编辑按钮
									size: 'small',
								},

								save: {  //行编辑模式保存按钮
									size: 'small',
								},

								remove: {  //行编辑模式保存按钮
									size: 'small',
								},
								cancel: {  //行编辑模式保存按钮
									size: 'small',
								},

						},
						},
						// 注释编号:django-vue3-admin-settings324009:代码结束行


					},
					// 注释编号:django-vue3-admin__settings344115:代码结束行

					form: {
						// 注释编号:django-vue3-admin__settings364715:代码开始行
						// 功能说明:这里专门针对form进行全局样式排版，以免每个页面都在带这些配置
						col: { span: 12 },	//配置成一行两个元素
						labelPosition: "left",
						labelWidth: "auto", //配置成lable的宽为自动
						requireAsteriskPosition:"right", //星号的位置
						row: { gutter: 40 } ,  //配置同一行内，两个元素之间空隙40px
						// 注释编号:django-vue3-admin__settings364715:代码结束行

						// 注释编号:django-vue3-admin__settings015815:代码开始行
						// 功能说明:配置全局的tabs组的显示效果
						group: {
							groupType: "tabs",
							accordion: false,
						},
						// 注释编号:django-vue3-admin__settings015815:代码结束行


						// 注释编号:workspace.json__settings093116:代码开始行
						// 功能说明:
						// wrapper: {
						// 	inner:true, //Dialog窗口取消遮罩层,做内联窗口,使tags可切换
						// },
						// 注释编号:workspace.json__settings093116:代码结束行


						// 注释编号:django-vue3-admin__settings094810:代码开始行
						// 功能说明:对于提交数据之后，进行检验，如果2000就是成功更新，而4000便是出现错误，这里就阻止提交数据，不关闭窗口
						afterSubmit(ctx: any) {
							// 增加crud提示
							if (ctx.res.code == 2000) {
								successNotification(ctx.res.msg);
								}
							else if (ctx.res.code == 4000){
								return false  //作者已经修复了这个问题 注释编号:django-vue3-admin__settings065210:这里未来fastcrud作者可能会改为直接返回false便可，期待https://github.com/fast-crud/fast-crud/issues/270

								}
						},
					},
					// 注释编号:django-vue3-admin__settings094810:代码结束行


					columns:{
						_index: {
							title: '序号',
							form: { show: false },
							column: {
								type: 'index',
								align: 'center',
								width: '70px',
							},
						},
						id: {
							title: 'ID',
							type: 'text',
							column: { show: false },
							search: { show: false },
							form: { show: false },
						},
						update_datetime: {
							title: '更新时间',
							type: 'text',
							search: { show: false },
							column: {
								show: false,
								width: 170,
								sortable: 'custom',
								order:990,
							},
							form: {
								show: false,
								component: {
									placeholder: '输入关键词搜索',
								},
							},
						},
						create_datetime: {
							title: '创建时间',
							type: 'text',
							search: { show: false },
							column: {
								show: false,
								sortable: 'custom',
								width: 170,
								order:1000,
							},
							form: {
								show: false,
								component: {
									placeholder: '输入关键词搜索',
								},
							},
						},
						// description: {
						// 	title: '备注',
						// 	type: 'textarea',
						// 	search: {show: false},
						// 	form: {
						// 		component: {
						// 		maxlength: 200,
						// 		placeholder: '输入备注',
						// 		},
						// 	},
						// },

					},

					// 注释编号:django-vue3-admin__settings260216:不建议配置search全局的搜索样式，因为有一些情况下，效果会好丑的
					/* search: {
						layout: 'multi-line',
						collapse: true,
						col: {
							span: 4,
						},
						options: {
							labelCol: {
								style: {
									width: '100px',
								},
							},
						},
					}, */
				};
			},
		});
		//富文本
		app.use(FsExtendsEditor, {
			wangEditor: {
				width: 300,
			},
		});
        // 文件上传
        app.use(FsExtendsUploader, {
            defaultType: "form",
            form: {
                action: `/api/system/file/`,
                name: "file",
                withCredentials: false,
                uploadRequest: async ({action, file, onProgress}) => {
                    // @ts-ignore
                    const data = new FormData();
                    data.append("file", file);
                    return await request({
                        url: action,
                        method: "post",
                        timeout: 60000,
                        headers: {
                            "Content-Type": "multipart/form-data"
                        },
                        data,
                        onUploadProgress: (p) => {
                            onProgress({percent: Math.round((p.loaded / p.total) * 100)});
                        }
                    });
                },
                successHandle(ret) {
                    // 上传完成后的结果处理， 此处应返回格式为{url:xxx,key:xxx}
                    return {
                        url: getBaseURL(ret.data.url),
                        key: ret.data.id,
                        ...ret.data
                    };
                }
            },
                valueBuilder(context){
                    const {row,key} = context
                    return getBaseURL(row[key])
                }
        })
		// 注释编号:django-vue3-admin__settings492314:代码开始行
		// 功能说明:配置了fastcurd的日志级别
		// setLogger({ level: 'error' });
		// setLogger({ level: 'info' });  //在这个级别下,虽然信息很多,但是可以查看到fastcrut的inited日志,方便自己查看都有什么配置项目
		// 注释编号:django-vue3-admin__settings492314:代码结束行

		// 设置自动染色
        // 设置自动染色
        const dictComponentList = ['dict-cascader', 'dict-checkbox', 'dict-radio', 'dict-select', 'dict-switch', 'dict-tree'];
        dictComponentList.forEach((val) => {
            getType(val).column.component.color = 'auto';
            getType(val).column.align = 'center';
        });

		// 设置placeholder 的默认值
        const placeholderComponentList = [
            {key: 'text', placeholder: "请输入"},
            {key: 'textarea', placeholder: "请输入"},
            {key: 'input', placeholder: "请输入"},
            {key: 'password', placeholder: "请输入"}
        ]
        placeholderComponentList.forEach((val) => {
            if (getType(val.key)?.search?.component) {
                getType(val.key).search.component.placeholder = val.placeholder;
            } else if (getType(val.key)?.search) {
                getType(val.key).search.component = {placeholder: val.placeholder};
            }
            if (getType(val.key)?.form?.component) {
                getType(val.key).form.component.placeholder = val.placeholder;
            } else if (getType(val.key)?.form) {
                getType(val.key).form.component = {placeholder: val.placeholder};
            }
            if (getType(val.key)?.column?.align) {
                getType(val.key).column.align = 'center'
            } else if (getType(val.key)?.column) {
                getType(val.key).column = {align: 'center'};
            } else if (getType(val.key)) {
                getType(val.key).column = {align: 'center'};
            }
        });







	},
};
