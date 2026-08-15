export interface ToolCost {
	id?: number;
	tool_category: number;
	cost_type: 'NEW_TOOL' | 'REPAIR';
	brand?: string;
	manufacturer?: string;
	unit_price?: number;
	repair_parts?: string[];
	remark?: string;
	create_datetime?: string;
	update_datetime?: string;
}
