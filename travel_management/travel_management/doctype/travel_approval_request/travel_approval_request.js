// Copyright (c) 2026, MDQuality Apps Solutions LLP
// Client-side script for Travel Request.
//
// Adapted from the "Polaris Project" package: workflow-transition buttons
// (Approve, Reject, etc.) are rendered natively by Frappe's Workflow engine
// once a Workflow is attached to this doctype, so this script only adds the
// calculations, field visibility and the extra convenience buttons that
// aren't already covered by the workflow.

const USD_TO_INR_FALLBACK = 85;

// Sections that aren't already gated by a field permlevel - shown only to the
// roles that actually act on that data, so each role's screen only carries
// the sections relevant to their part of the trip (booking, insurance, forex).
// System Manager, Travel Manager and the traveling Employee always see
// everything else regardless of this map (oversight / it's their own trip).
const ROLE_SCOPED_SECTIONS = {
	section_break_flight: ["Travel Agent", "Finance Approver"],
	section_break_hotel: ["Travel Agent", "Finance Approver"],
	section_break_hotel2: ["Travel Agent", "Finance Approver"],
	section_break_perdiem: ["Travel Agent", "Finance Approver"],
	section_break_insurance: ["Travel Coordinator", "Forex Card Processor", "Finance Approver"],
	section_break_forex: ["Travel Coordinator", "Forex Card Processor"],
};
const ALWAYS_FULL_ACCESS_ROLES = ["System Manager", "Travel Manager"];

frappe.ui.form.on("Travel Approval Request", {
	onload(frm) {
		toggle_extension_fields(frm);
		set_cost_fields_readonly(frm);
		frm.set_query("hotel_name", () => ({
			filters: { reference_type: "Hotel", status: "Active" },
		}));
		frm.set_query("hotel_name_2", () => ({
			filters: { reference_type: "Hotel", status: "Active" },
		}));
	},

	refresh(frm) {
		frm.page.clear_indicator();
		apply_role_scoped_sections(frm);
		show_cost_summary(frm);
		show_pending_action(frm);
		add_extra_buttons(frm);
	},

	destination(frm) {
		set_per_diem_rate(frm);
		suggest_hotels(frm);
	},

	travel_from_date(frm) {
		if (!frm.doc.travel_from_date) return;
		const today = frappe.datetime.now_date();
		if (frm.doc.travel_from_date <= today) {
			frappe.msgprint(__("Travel From Date must be in the future"));
			frm.set_value("travel_from_date", "");
			return;
		}
		if (!frm.doc.hotel_checkin_date) {
			frm.set_value("hotel_checkin_date", frm.doc.travel_from_date);
		}
		calculate_per_diem(frm);
	},

	travel_to_date(frm) {
		if (!frm.doc.travel_to_date) return;
		if (frm.doc.travel_from_date && frm.doc.travel_to_date <= frm.doc.travel_from_date) {
			frappe.msgprint(__("Travel To Date must be after From Date"));
			frm.set_value("travel_to_date", "");
			return;
		}
		if (!frm.doc.hotel_checkout_date) {
			frm.set_value("hotel_checkout_date", frm.doc.travel_to_date);
		}
		calculate_per_diem(frm);
	},

	employee(frm) {
		if (!frm.doc.employee) return;
		frappe.call({
			method: "frappe.client.get_count",
			args: {
				doctype: "Travel Approval Request",
				filters: { employee: frm.doc.employee, docstatus: 1 },
			},
			callback(r) {
				if (r.message === 0) {
					frm.set_value("is_first_time_traveler", 1);
					frm.set_value("forex_card_suggested", 1);
					frm.set_value("forex_card_emergency_buffer", 500);
					frappe.show_alert({ message: __("First-time traveler detected - forex card setup suggested"), indicator: "blue" });
				}
			},
		});
	},

	estimated_flight_fare_usd(frm) {
		frm.set_value("estimated_flight_fare", (frm.doc.estimated_flight_fare_usd || 0) * USD_TO_INR_FALLBACK);
		check_flight_approval_required(frm);
		calculate_total_cost(frm);
	},

	hotel_name(frm) {
		if (!frm.doc.hotel_name) return;
		frappe.call({
			method: "frappe.client.get",
			args: { doctype: "Travel Reference Master", name: frm.doc.hotel_name },
			callback(r) {
				if (!r.message) return;
				frm.set_value("hotel_daily_rate_usd", r.message.usd_rate);
				frm.set_value("hotel_daily_rate_inr", r.message.inr_rate);
				frm.set_value("hotel_currency", r.message.local_currency);
				check_hotel_approval_required(frm);
				calculate_hotel_costs(frm);
			},
		});
	},

	hotel_checkin_date(frm) {
		calculate_hotel_costs(frm);
	},

	hotel_checkout_date(frm) {
		calculate_hotel_costs(frm);
	},

	hotel_name_2(frm) {
		if (!frm.doc.hotel_name_2) return;
		frappe.call({
			method: "frappe.client.get",
			args: { doctype: "Travel Reference Master", name: frm.doc.hotel_name_2 },
			callback(r) {
				if (!r.message) return;
				frm.set_value("hotel_daily_rate_usd_2", r.message.usd_rate);
				frm.set_value("hotel_daily_rate_inr_2", r.message.inr_rate);
				frm.set_value("hotel_currency_2", r.message.local_currency);
				check_hotel_approval_required_2(frm);
				calculate_hotel_costs_2(frm);
			},
		});
	},

	hotel_checkin_date_2(frm) {
		calculate_hotel_costs_2(frm);
	},

	hotel_checkout_date_2(frm) {
		calculate_hotel_costs_2(frm);
	},

	travel_insurance_cost_usd(frm) {
		sync_insurance_cost_inr(frm);
		calculate_total_cost(frm);
	},

	health_insurance_cost_usd(frm) {
		sync_insurance_cost_inr(frm);
		calculate_total_cost(frm);
	},

	forex_card_amount_loaded(frm) {
		calculate_total_cost(frm);
	},

	forex_misc_amount(frm) {
		calculate_total_cost(frm);
	},

	is_extension(frm) {
		toggle_extension_fields(frm);
	},
});

function apply_role_scoped_sections(frm) {
	const is_owner = frm.doc.owner === frappe.session.user;
	const roles = frappe.user_roles || [];
	const has_full_access = is_owner || roles.some((role) => ALWAYS_FULL_ACCESS_ROLES.includes(role));

	Object.entries(ROLE_SCOPED_SECTIONS).forEach(([section, allowed_roles]) => {
		const show = has_full_access || roles.some((role) => allowed_roles.includes(role));
		frm.toggle_display(section, show);
	});
}

function toggle_extension_fields(frm) {
	frm.refresh_field("original_travel_request");
	frm.refresh_field("extended_from_date");
	frm.refresh_field("extended_to_date");
}

function set_cost_fields_readonly(frm) {
	["total_per_diem", "total_hotel_cost_usd", "total_hotel_cost_inr", "total_hotel_cost_usd_2", "total_hotel_cost_inr_2", "total_estimated_cost"].forEach((f) =>
		frm.set_df_property(f, "read_only", 1)
	);
}

function set_per_diem_rate(frm) {
	if (!frm.doc.destination) return;
	frappe.call({
		method: "travel_management.travel_management.doctype.travel_approval_request.travel_approval_request.get_per_diem_rate",
		args: { destination: frm.doc.destination },
		callback(r) {
			if (r.message) {
				frm.set_value("per_diem_rate", r.message);
				calculate_per_diem(frm);
			}
		},
	});
}

function calculate_per_diem(frm) {
	if (!frm.doc.travel_from_date || !frm.doc.travel_to_date) return;

	const from_date = frappe.datetime.str_to_obj(frm.doc.travel_from_date);
	const to_date = frappe.datetime.str_to_obj(frm.doc.travel_to_date);
	const days = Math.floor((to_date - from_date) / 86400000) + 1;

	frm.set_value("travel_days", days);

	const rate = frm.doc.per_diem_rate || 70;
	frm.set_value("total_per_diem", days * rate);
	frm.set_value("per_diem_currency", "USD");
	calculate_total_cost(frm);
}

function suggest_hotels(frm) {
	if (!frm.doc.destination) return;
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Travel Reference Master",
			filters: { reference_type: "Hotel", city: frm.doc.destination, status: "Active" },
			fields: ["name", "usd_rate", "inr_rate"],
		},
		callback(r) {
			if (r.message && r.message.length) {
				const options = r.message.map((h) => `${h.name} (USD ${h.usd_rate})`).join(", ");
				frappe.show_alert({ message: __("Approved hotels: {0}", [options]), indicator: "blue" }, 5);
			}
		},
	});
}

function calculate_hotel_costs(frm) {
	if (!frm.doc.hotel_checkin_date || !frm.doc.hotel_checkout_date || !frm.doc.hotel_daily_rate_usd) return;

	const check_in = frappe.datetime.str_to_obj(frm.doc.hotel_checkin_date);
	const check_out = frappe.datetime.str_to_obj(frm.doc.hotel_checkout_date);
	const nights = Math.floor((check_out - check_in) / 86400000);

	frm.set_value("hotel_nights", nights);
	const total_usd = nights * frm.doc.hotel_daily_rate_usd;
	frm.set_value("total_hotel_cost_usd", total_usd);
	frm.set_value("total_hotel_cost_inr", total_usd * USD_TO_INR_FALLBACK);
	calculate_total_cost(frm);
}

function calculate_hotel_costs_2(frm) {
	if (!frm.doc.hotel_checkin_date_2 || !frm.doc.hotel_checkout_date_2 || !frm.doc.hotel_daily_rate_usd_2) return;

	const check_in = frappe.datetime.str_to_obj(frm.doc.hotel_checkin_date_2);
	const check_out = frappe.datetime.str_to_obj(frm.doc.hotel_checkout_date_2);
	const nights = Math.floor((check_out - check_in) / 86400000);

	frm.set_value("hotel_nights_2", nights);
	const total_usd = nights * frm.doc.hotel_daily_rate_usd_2;
	frm.set_value("total_hotel_cost_usd_2", total_usd);
	frm.set_value("total_hotel_cost_inr_2", total_usd * USD_TO_INR_FALLBACK);
	calculate_total_cost(frm);
}

function check_flight_approval_required(frm) {
	if (!frm.doc.estimated_flight_fare) return;
	const required = frm.doc.estimated_flight_fare >= 50000;
	frm.set_value("flight_approval_required", required ? 1 : 0);
	frm.set_value("flight_approval_by", required ? "Finance Approver" : "");
	if (required) {
		frappe.show_alert({ message: __("Flight fare exceeds Rs.50,000 - Finance Approver sign-off required"), indicator: "orange" }, 5);
	}
}

function check_hotel_approval_required(frm) {
	if (!frm.doc.hotel_daily_rate_usd) return;
	const required = frm.doc.hotel_daily_rate_usd > 97;
	frm.set_value("hotel_approval_required", required ? 1 : 0);
	frm.set_value("hotel_approval_by", required ? "Finance Approver" : "");
	if (required) {
		frappe.show_alert({ message: __("Hotel rate is above USD 97 - Finance Approver sign-off required"), indicator: "orange" }, 5);
	}
}

function check_hotel_approval_required_2(frm) {
	if (!frm.doc.hotel_daily_rate_usd_2) return;
	const required = frm.doc.hotel_daily_rate_usd_2 > 97;
	frm.set_value("hotel_approval_required_2", required ? 1 : 0);
	frm.set_value("hotel_approval_by_2", required ? "Finance Approver" : "");
	if (required) {
		frappe.show_alert({ message: __("Oman hotel rate is above USD 97 - Finance Approver sign-off required"), indicator: "orange" }, 5);
	}
}

function sync_insurance_cost_inr(frm) {
	const total_usd = (frm.doc.travel_insurance_cost_usd || 0) + (frm.doc.health_insurance_cost_usd || 0);
	frm.set_value("insurance_estimated_cost", total_usd * USD_TO_INR_FALLBACK);
}

function calculate_total_cost(frm) {
	// Every component here is USD-native - plain sum, no exchange rate.
	let total = 0;
	total += frm.doc.estimated_flight_fare_usd || 0;
	total += frm.doc.total_hotel_cost_usd || 0;
	if (frm.doc.destination === "Both") {
		total += frm.doc.total_hotel_cost_usd_2 || 0;
	}
	total += frm.doc.total_per_diem || 0;
	total += frm.doc.travel_insurance_cost_usd || 0;
	total += frm.doc.health_insurance_cost_usd || 0;
	total += frm.doc.forex_card_amount_loaded || 0;
	total += frm.doc.forex_misc_amount || 0;
	frm.set_value("total_estimated_cost", total);
}

function show_cost_summary(frm) {
	if (frm.doc.__islocal) return;
	const total = frm.doc.total_estimated_cost || 0;
	frm.dashboard.set_headline_alert(
		`<div class="row"><div class="col-xs-12"><span class="indicator-pill blue">${__("Total Estimated Cost")}: $ ${total.toLocaleString("en-US")}</span></div></div>`
	);
}

function show_pending_action(frm) {
	if (frm.doc.__islocal || !frm.doc.workflow_state) return;
	const state = __(frm.doc.workflow_state);
	const pending = frm.doc.pending_action;
	const message =
		pending && pending !== "No pending actions" ? `${state} — ${__("Pending")}: ${pending}` : state;
	frm.dashboard.add_comment(message, "orange", true);
}

function add_extra_buttons(frm) {
	if (frm.doc.docstatus !== 1) return;

	frm.add_custom_button(__("Export Travel Brief"), () => {
		frappe.set_route("print", frm.doc.doctype, frm.doc.name);
	});

	if (
		frm.doc.workflow_state === "Ready for Travel" ||
		frm.doc.workflow_state === "Travel In Progress" ||
		frm.doc.workflow_state === "Travel Completed"
	) {
		frm.add_custom_button(__("Request Extension"), () => {
			const today = frappe.datetime.now_date();
			// Extension starts the day after the original trip ends, or
			// tomorrow if that date has already passed - either way it must
			// satisfy the "Travel From Date must be in the future" rule.
			const original_end = frm.doc.travel_to_date;
			const ext_from =
				original_end && original_end > today
					? frappe.datetime.add_days(original_end, 1)
					: frappe.datetime.add_days(today, 1);
			const ext_to = frappe.datetime.add_days(ext_from, 2);

			frappe.new_doc("Travel Approval Request", {
				employee: frm.doc.employee,
				employee_name: frm.doc.employee_name,
				designation: frm.doc.designation,
				department: frm.doc.department,
				manager: frm.doc.manager,
				destination: frm.doc.destination,
				trip_purpose: frm.doc.trip_purpose,
				travel_from_date: ext_from,
				travel_to_date: ext_to,
				per_diem_rate: frm.doc.per_diem_rate,
				per_diem_currency: frm.doc.per_diem_currency,
				visa_contact: frm.doc.visa_contact,
				visa_contact_email: frm.doc.visa_contact_email,
				visa_country: frm.doc.visa_country,
				is_extension: 1,
				original_travel_request: frm.doc.name,
				extended_from_date: ext_from,
				extended_to_date: ext_to,
			});
		});
	}

	if (frm.doc.workflow_state === "Travel Completed" && frappe.model.can_create("Travel Expense Report")) {
		frm.add_custom_button(__("Create Expense Report"), () => {
			frappe.call({
				method: "travel_management.travel_management.doctype.travel_approval_request.travel_approval_request.create_expense_report",
				args: { travel_request_id: frm.doc.name },
				callback(r) {
					if (r.message) {
						frappe.set_route("form", "Travel Expense Report", r.message.name);
					}
				},
			});
		});
	}
}
