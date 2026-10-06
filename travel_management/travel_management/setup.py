# Copyright (c) 2026, MDQuality Apps Solutions LLP
"""One-time setup: roles, reference master data, and the Travel Approval Workflow.

Run with:
    bench --site <site> execute travel_management.travel_management.setup.bootstrap

Safe to re-run - every step checks for existing records first.
"""

import frappe

ROLES = [
	"Travel Manager",
	"Travel Coordinator",
	"Visa Contact",
	"Approval Authority",
	"Finance Approver",
	"Travel Agent",
	"Forex Card Processor",
]

REFERENCE_DATA = [
	# Hotels
	dict(
		reference_name="Hilton Garden Inn, Muscat",
		reference_type="Hotel",
		city="Muscat",
		local_currency="OMR",
		local_rate=37,
		usd_rate=96.2,
		inr_rate=8905.6,
		approval_threshold=97,
	),
	dict(
		reference_name="Doubletree by Hilton, Doha",
		reference_type="Hotel",
		city="Doha",
		local_currency="QAR",
		local_rate=350,
		usd_rate=95.95,
		inr_rate=8856.85,
		approval_threshold=97,
	),
	dict(
		reference_name="Centro Rotana Hotel, Doha",
		reference_type="Hotel",
		city="Doha",
		local_currency="QAR",
		local_rate=350,
		usd_rate=60.75,
		inr_rate=5042.25,
		approval_threshold=97,
	),
	# Per Diem
	dict(
		reference_name="Doha, Qatar",
		reference_type="Per Diem",
		destination="Doha, Qatar",
		rate=70,
		day_counting_rule="Arrival & departure = full day",
	),
	dict(
		reference_name="Muscat, Oman",
		reference_type="Per Diem",
		destination="Muscat, Oman",
		rate=70,
		day_counting_rule="Arrival & departure = full day",
	),
	# Insurance
	dict(
		reference_name="Qatar Insurance",
		reference_type="Insurance",
		destination="Qatar",
		insurance_type="ICICI Lombard + Qatar Mandatory Visitor Health",
		provider="ICICI Lombard",
		coverage_details="Min 30 days coverage",
		min_days=30,
	),
	dict(
		reference_name="Oman Insurance",
		reference_type="Insurance",
		destination="Oman",
		insurance_type="ICICI Lombard",
		provider="ICICI Lombard",
		coverage_details="Exact travel dates coverage",
	),
	# Approvers / Contacts (placeholder emails - update with real addresses)
	dict(
		reference_name="Manlio - Approver",
		reference_type="Approver",
		contact_role="Approval Authority",
		email="manlio@example.com",
		responsibility="Travel Approval",
	),
	dict(
		reference_name="Alberto - Approver",
		reference_type="Approver",
		contact_role="Exception Approver",
		email="alberto@example.com",
		responsibility="Fare & Hotel Approval",
	),
	dict(
		reference_name="Peter - Approver",
		reference_type="Approver",
		contact_role="Process Owner",
		email="peter@example.com",
		responsibility="Budget Approval",
	),
	dict(
		reference_name="Sunil - Visa Contact",
		reference_type="Approver",
		destination="Qatar",
		contact_role="Qatar Visa",
		email="sunil@example.com",
		responsibility="Qatar Visa Processing",
	),
	dict(
		reference_name="Sadiq - Visa Contact",
		reference_type="Approver",
		destination="Oman",
		contact_role="Oman Visa",
		email="sadiq@example.com",
		responsibility="Oman Visa Processing",
	),
	dict(
		reference_name="Asha - Coordinator",
		reference_type="Approver",
		contact_role="Travel Coordinator",
		email="asha@example.com",
		responsibility="Travel Coordination",
	),
	dict(
		reference_name="Krishna - Forex",
		reference_type="Approver",
		contact_role="Finance",
		email="krishna@example.com",
		responsibility="Forex Card Processing",
	),
]

# (state, doc_status, style, allow_edit_role)
WORKFLOW_STATES = [
	("Draft", "0", "", "Travel Manager"),
	("Manager Request", "1", "Info", "Travel Manager"),
	("TA Preparation", "1", "Primary", "Travel Coordinator"),
	("Visa Routing", "1", "Info", "Visa Contact"),
	("Visa Approved", "1", "Success", "Visa Contact"),
	("Manager Approval", "1", "Warning", "Approval Authority"),
	("Approval Granted", "1", "Success", "Approval Authority"),
	("Manager Green Light", "1", "Success", "Travel Manager"),
	("Flight Booking", "1", "Warning", "Travel Agent"),
	("Fare Approval", "1", "Warning", "Finance Approver"),
	("Hotel Booking", "1", "Warning", "Travel Agent"),
	("Hotel Approval", "1", "Warning", "Finance Approver"),
	("Insurance Processing", "1", "Warning", "Travel Coordinator"),
	("Forex Card Setup", "1", "Info", "Forex Card Processor"),
	("Ready for Travel", "1", "Success", "Employee"),
	("Travel In Progress", "1", "Info", "Employee"),
	("Travel Completed", "1", "Success", "Employee"),
	("Expense Report Pending", "1", "Warning", "Employee"),
	("Final Settlement", "1", "Success", "Finance Approver"),
	("Rejected", "1", "Danger", "Travel Manager"),
	("Cancelled", "1", "Inverse", "Travel Manager"),
]

# (from_state, action, to_state, role, condition)
CANCEL_FROM_STATES = [
	"Manager Request",
	"TA Preparation",
	"Visa Routing",
	"Visa Approved",
	"Manager Approval",
	"Approval Granted",
	"Manager Green Light",
	"Flight Booking",
	"Fare Approval",
	"Hotel Booking",
	"Hotel Approval",
	"Insurance Processing",
	"Forex Card Setup",
	"Ready for Travel",
	"Travel In Progress",
]

# (from_state, action, to_state, role, condition, allow_self_approval)
# allow_self_approval is needed wherever the acting role is normally the same
# person who owns (created/submitted) the document - e.g. the traveling
# employee submitting their own request or marking their own trip started -
# Frappe's workflow engine blocks an owner from actioning their own document
# by default (WorkflowPermissionError: "Self approval is not allowed").
WORKFLOW_TRANSITIONS = [
	("Draft", "Submit Travel Request", "Manager Request", "Travel Manager", None, True),
	(
		"Draft",
		"Submit Travel Request",
		"Manager Request",
		"Employee",
		"frappe.session.user == doc.employee_email",
		True,
	),
	("Manager Request", "Confirm & Request TA Form", "TA Preparation", "Travel Manager", None, True),
	(
		"TA Preparation",
		"Complete & Route to Visa Contact",
		"Visa Routing",
		"Travel Coordinator",
		"doc.estimated_flight_fare",
		False,
	),
	("TA Preparation", "Return for Changes", "Manager Request", "Travel Coordinator", None, False),
	("Visa Routing", "Confirm Visa Approved", "Visa Approved", "Visa Contact", None, False),
	("Visa Approved", "Route to Manlio Approval", "Manager Approval", "Visa Contact", None, False),
	("Manager Approval", "Approve Travel", "Approval Granted", "Approval Authority", None, False),
	("Manager Approval", "Reject (Request Changes)", "Manager Request", "Approval Authority", None, False),
	(
		"Approval Granted",
		"Confirm Green Light & Proceed",
		"Manager Green Light",
		"Travel Manager",
		None,
		True,
	),
	(
		"Manager Green Light",
		"Route to Fare Approval",
		"Fare Approval",
		"Travel Coordinator",
		"doc.estimated_flight_fare and doc.estimated_flight_fare >= 50000",
		False,
	),
	(
		"Manager Green Light",
		"Proceed to Flight Booking",
		"Flight Booking",
		"Travel Coordinator",
		"doc.estimated_flight_fare and doc.estimated_flight_fare < 50000",
		False,
	),
	("Fare Approval", "Approve Fare & Proceed", "Flight Booking", "Finance Approver", None, False),
	("Fare Approval", "Reject (Too High)", "Manager Green Light", "Finance Approver", None, False),
	("Flight Booking", "Issue Tickets & Move to Hotel", "Hotel Booking", "Travel Agent", None, False),
	(
		"Hotel Booking",
		"Route to Hotel Approval",
		"Hotel Approval",
		"Travel Agent",
		"(doc.destination != 'Both' and doc.hotel_daily_rate_usd and doc.hotel_daily_rate_usd > 97)"
		" or (doc.destination == 'Both' and doc.hotel_daily_rate_usd and doc.hotel_daily_rate_usd_2"
		" and (doc.hotel_daily_rate_usd > 97 or doc.hotel_daily_rate_usd_2 > 97))",
		False,
	),
	(
		"Hotel Booking",
		"Confirm Hotel & Move to Insurance",
		"Insurance Processing",
		"Travel Agent",
		"(doc.destination != 'Both' and doc.hotel_daily_rate_usd and doc.hotel_daily_rate_usd <= 97)"
		" or (doc.destination == 'Both' and doc.hotel_daily_rate_usd and doc.hotel_daily_rate_usd_2"
		" and doc.hotel_daily_rate_usd <= 97 and doc.hotel_daily_rate_usd_2 <= 97)",
		False,
	),
	("Hotel Approval", "Approve Hotel & Proceed", "Insurance Processing", "Finance Approver", None, False),
	("Hotel Approval", "Reject (Too High)", "Hotel Booking", "Finance Approver", None, False),
	(
		"Insurance Processing",
		"Complete Insurance & Setup Forex",
		"Forex Card Setup",
		"Travel Coordinator",
		"doc.insurance_estimated_cost and doc.is_first_time_traveler == 1",
		False,
	),
	(
		"Insurance Processing",
		"Complete Insurance",
		"Ready for Travel",
		"Travel Coordinator",
		"doc.insurance_estimated_cost and doc.is_first_time_traveler != 1",
		False,
	),
	(
		"Forex Card Setup",
		"Activate Card & Complete Setup",
		"Ready for Travel",
		"Forex Card Processor",
		"doc.forex_card_amount_loaded",
		False,
	),
	(
		"Forex Card Setup",
		"Activate Card & Complete Setup",
		"Ready for Travel",
		"Travel Coordinator",
		"doc.forex_card_amount_loaded",
		False,
	),
	(
		"Ready for Travel",
		"Mark as Travel Started",
		"Travel In Progress",
		"Employee",
		"frappe.session.user == doc.employee_email",
		True,
	),
	("Ready for Travel", "Mark as Travel Started", "Travel In Progress", "Travel Manager", None, True),
	(
		"Travel In Progress",
		"Mark Travel Complete",
		"Travel Completed",
		"Employee",
		"frappe.session.user == doc.employee_email",
		True,
	),
	("Travel In Progress", "Mark Travel Complete", "Travel Completed", "Travel Manager", None, True),
	(
		"Travel Completed",
		"Awaiting Expense Report",
		"Expense Report Pending",
		"Employee",
		"frappe.session.user == doc.employee_email",
		True,
	),
	("Expense Report Pending", "Process & Settle", "Final Settlement", "Finance Approver", None, False),
	("Expense Report Pending", "Reject (Non-Compliant)", "Rejected", "Finance Approver", None, False),
	("Rejected", "Resubmit", "Manager Request", "Travel Manager", None, True),
] + [(state, "Cancel Travel", "Cancelled", "Travel Manager", None, False) for state in CANCEL_FROM_STATES]

ADMIN_ROLE = "System Manager"


def create_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def create_reference_master_data():
	for row in REFERENCE_DATA:
		if frappe.db.exists("Travel Reference Master", row["reference_name"]):
			continue
		doc = frappe.new_doc("Travel Reference Master")
		doc.update(row)
		doc.status = "Active"
		doc.insert(ignore_permissions=True)


def _build_transition_rows():
	rows = []
	seen = set()
	for from_state, action, to_state, role, condition, allow_self_approval in WORKFLOW_TRANSITIONS:
		rows.append(
			{
				"state": from_state,
				"action": action,
				"next_state": to_state,
				"allowed": role,
				"condition": condition,
				"allow_self_approval": 1 if allow_self_approval else 0,
			}
		)
		key = (from_state, action, to_state)
		if key not in seen:
			seen.add(key)
			rows.append(
				{
					"state": from_state,
					"action": action,
					"next_state": to_state,
					"allowed": ADMIN_ROLE,
					"condition": condition,
					"allow_self_approval": 1,
				}
			)
	return rows


def create_workflow_masters():
	for state, _doc_status, style, _allow_edit in WORKFLOW_STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": style or ""}
			).insert(ignore_permissions=True)

	actions = {action for _f, action, _t, _r, _c, _sa in WORKFLOW_TRANSITIONS}
	for action in actions:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)


def create_workflow():
	if frappe.db.exists("Workflow", "Travel Approval Workflow"):
		return

	create_workflow_masters()

	doc = frappe.new_doc("Workflow")
	doc.workflow_name = "Travel Approval Workflow"
	doc.document_type = "Travel Approval Request"
	doc.workflow_state_field = "workflow_state"
	doc.is_active = 1
	doc.send_email_alert = 0

	for state, doc_status, style, allow_edit in WORKFLOW_STATES:
		doc.append(
			"states",
			{"state": state, "doc_status": doc_status, "style": style, "allow_edit": allow_edit},
		)

	for row in _build_transition_rows():
		doc.append("transitions", row)

	doc.insert(ignore_permissions=True)


EMAIL_TEMPLATES = [
	{
		"name": "Travel TA Form Preparation Request",
		"subject": "Action Required: Travel Authorization Form - {{ name }}",
		"response": (
			"<p>Dear Coordinator,</p>"
			"<p>A new travel request requires your attention:</p>"
			"<ul>"
			"<li><b>Employee:</b> {{ employee_name }}</li>"
			"<li><b>Destination:</b> {{ destination }}</li>"
			"<li><b>Travel Dates:</b> {{ travel_from_date }} to {{ travel_to_date }}</li>"
			"<li><b>Purpose:</b> {{ trip_purpose }}</li>"
			"</ul>"
			"<p>Please prepare the Travel Authorization Form and route it to the visa contact.</p>"
		),
	},
	{
		"name": "Travel Visa Routing Notification",
		"subject": "Travel Visa Processing - {{ destination }} - {{ name }}",
		"response": (
			"<p>Dear {{ visa_contact }},</p>"
			"<p>A Travel Authorization Form requires visa processing:</p>"
			"<ul>"
			"<li><b>Employee:</b> {{ employee_name }}</li>"
			"<li><b>Destination:</b> {{ destination }}</li>"
			"<li><b>Travel Dates:</b> {{ travel_from_date }} to {{ travel_to_date }}</li>"
			"</ul>"
			"<p>Please process the visa and route to the Approval Authority once complete.</p>"
		),
	},
	{
		"name": "Travel Approval Request - Approval Authority",
		"subject": "Travel Authorization Approval Required - {{ employee_name }}",
		"response": (
			"<p>Dear Approving Authority,</p>"
			"<p>Travel request requires your approval:</p>"
			"<ul>"
			"<li><b>Employee:</b> {{ employee_name }}</li>"
			"<li><b>Destination:</b> {{ destination }}</li>"
			"<li><b>Travel Dates:</b> {{ travel_from_date }} to {{ travel_to_date }}</li>"
			"<li><b>Visa Status:</b> {{ visa_status }}</li>"
			"<li><b>Estimated Cost:</b> USD {{ total_estimated_cost }}</li>"
			"</ul>"
			"<p>Please review and approve for the travel to proceed.</p>"
		),
	},
	{
		"name": "Travel Booking Request - Travel Agent",
		"subject": "Travel Booking Request - {{ employee_name }} ({{ destination }})",
		"response": (
			"<p>Dear Travel Agent,</p>"
			"<p>Travel is approved. Please proceed with bookings:</p>"
			"<p><b>Passenger:</b> {{ employee_name }} ({{ employee }})</p>"
			"<p><b>Route:</b> {{ flight_route }}</p>"
			"<p><b>Travel Dates:</b> {{ travel_from_date }} to {{ travel_to_date }}</p>"
			"<p><b>Budget Limit:</b> USD {{ total_estimated_cost }}</p>"
			"<p><b>Hotel:</b> {{ hotel_name }}</p>"
		),
	},
	{
		"name": "Expense Report Submission Reminder",
		"subject": "Reminder: Submit Expense Report - {{ name }}",
		"response": (
			"<p>Dear {{ employee_name }},</p>"
			"<p>Your travel is completed. Please submit your expense report within 3 working days.</p>"
			"<ul>"
			"<li><b>Travel Request:</b> {{ name }}</li>"
			"<li><b>Destination:</b> {{ destination }}</li>"
			"<li><b>Travel Dates:</b> {{ travel_from_date }} to {{ travel_to_date }}</li>"
			"</ul>"
			"<p>Submit your expense report with all receipts and documentation.</p>"
		),
	},
]

# (name, document_type, value_changed, condition, recipients)
# recipients: list of ("role", <Role name>) or ("field", <fieldname holding an email>)
NOTIFICATIONS = [
	(
		"Travel - TA Form Preparation Request",
		"Travel Approval Request",
		"workflow_state",
		'doc.workflow_state == "TA Preparation"',
		[("role", "Travel Coordinator")],
		"Travel TA Form Preparation Request",
	),
	(
		"Travel - Visa Routing Notification",
		"Travel Approval Request",
		"workflow_state",
		'doc.workflow_state == "Visa Routing"',
		[("field", "visa_contact_email")],
		"Travel Visa Routing Notification",
	),
	(
		"Travel - Manager Approval Required",
		"Travel Approval Request",
		"workflow_state",
		'doc.workflow_state == "Manager Approval"',
		[("role", "Approval Authority")],
		"Travel Approval Request - Approval Authority",
	),
	(
		"Travel - Fare Approval Required",
		"Travel Approval Request",
		"workflow_state",
		'doc.workflow_state == "Fare Approval"',
		[("role", "Finance Approver")],
		"Travel Approval Request - Approval Authority",
	),
	(
		"Travel - Booking Request to Travel Agent",
		"Travel Approval Request",
		"workflow_state",
		'doc.workflow_state == "Flight Booking"',
		[("role", "Travel Agent")],
		"Travel Booking Request - Travel Agent",
	),
	(
		"Travel - Expense Report Reminder",
		"Travel Approval Request",
		"workflow_state",
		'doc.workflow_state == "Expense Report Pending"',
		[("field", "employee_email")],
		"Expense Report Submission Reminder",
	),
]

# SOP "Communication Protocol" (step 17): keep these stakeholders CC'd on
# every approval-stage communication. Alberto/Peter already have real
# accounts; Dharam/Mahesh are CC-only contacts in the SOP with no system
# role of their own, so placeholder addresses stand in for them here.
APPROVAL_CC = "alberto@example.com,peter@example.com,dharam@example.com,mahesh@example.com"
NOTIFICATIONS_WITH_CC = {
	"Travel - Visa Routing Notification",
	"Travel - Manager Approval Required",
	"Travel - Fare Approval Required",
}

# (name, description, condition, users, close_condition)
ASSIGNMENT_RULES = [
	(
		"Travel - Assign Coordinator for TA Preparation",
		"Prepare the Travel Authorization Form",
		'workflow_state == "TA Preparation"',
		["asha@example.com"],
		'workflow_state != "TA Preparation"',
	),
	(
		"Travel - Assign Visa Contact for Routing",
		"Process visa and route to the Approval Authority",
		'workflow_state == "Visa Routing"',
		["sunil@example.com", "sadiq@example.com"],
		'workflow_state != "Visa Routing"',
	),
	(
		"Travel - Assign Approval Authority",
		"Review and approve the travel request",
		'workflow_state == "Manager Approval"',
		["manlio@example.com"],
		'workflow_state != "Manager Approval"',
	),
	(
		"Travel - Assign Finance Approver for High Fare",
		"Approve flight fare above the policy threshold",
		'workflow_state == "Fare Approval"',
		["alberto@example.com", "peter@example.com"],
		'workflow_state != "Fare Approval"',
	),
]

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def create_email_templates():
	for tpl in EMAIL_TEMPLATES:
		if frappe.db.exists("Email Template", tpl["name"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": tpl["name"],
				"subject": tpl["subject"],
				"response": tpl["response"],
			}
		).insert(ignore_permissions=True)


def create_notifications():
	for name, doctype, value_changed, condition, recipients, _template in NOTIFICATIONS:
		if frappe.db.exists("Notification", name):
			continue

		template = next(t for t in EMAIL_TEMPLATES if t["name"] == _template)

		doc = frappe.new_doc("Notification")
		doc.subject = _as_doc_jinja(template["subject"])
		doc.document_type = doctype
		doc.event = "Value Change"
		doc.value_changed = value_changed
		doc.condition_type = "Python"
		doc.condition = condition
		doc.channel = "Email"
		doc.enabled = 1
		doc.message = _as_doc_jinja(template["response"])

		cc = APPROVAL_CC if name in NOTIFICATIONS_WITH_CC else ""
		for kind, value in recipients:
			row = {"condition": "", "cc": cc}
			if kind == "role":
				row["receiver_by_role"] = value
			else:
				row["receiver_by_document_field"] = value
			doc.append("recipients", row)

		doc.insert(ignore_permissions=True, set_name=name)


def _as_doc_jinja(html):
	"""EMAIL_TEMPLATES use Email Template's flattened {{ field }} syntax;
	Notification's subject/message need the {{ doc.field }} form instead."""
	import re

	return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", r"{{ doc.\1 }}", html)


def create_assignment_rules():
	for name, description, condition, users, close_condition in ASSIGNMENT_RULES:
		if frappe.db.exists("Assignment Rule", name):
			continue

		doc = frappe.new_doc("Assignment Rule")
		doc.name = name
		doc.document_type = "Travel Approval Request"
		doc.description = description
		doc.assign_condition = condition
		doc.close_condition = close_condition
		doc.rule = "Round Robin"
		doc.priority = 1
		doc.due_date_based_on = ""

		for user in users:
			doc.append("users", {"user": user})

		for day in WEEKDAYS:
			doc.append("assignment_days", {"day": day})

		doc.insert(ignore_permissions=True, set_name=name)


# (name, ref_doctype, roles, query)
REPORTS = [
	(
		"Travel Request Status Report",
		"Travel Approval Request",
		["Travel Manager", "Travel Coordinator", "Approval Authority", "Finance Approver"],
		"""
		SELECT
			name AS "Travel Request:Link/Travel Approval Request:150",
			employee_name AS "Employee:Data:150",
			destination AS "Destination:Data:100",
			workflow_state AS "Stage:Data:150",
			overall_status AS "Overall Status:Data:120",
			travel_from_date AS "From:Date:100",
			travel_to_date AS "To:Date:100",
			total_estimated_cost AS "Est. Cost (USD):Currency:130",
			pending_action AS "Pending Action:Data:280"
		FROM `tabTravel Approval Request`
		WHERE docstatus < 2
		ORDER BY travel_from_date DESC
		""",
	),
	(
		"Travel Budget Report",
		"Travel Budget Estimate",
		["Travel Manager", "Travel Coordinator", "Finance Approver", "Approval Authority"],
		"""
		SELECT
			name AS "Budget:Link/Travel Budget Estimate:150",
			period AS "Period:Data:120",
			status AS "Status:Data:100",
			total_budgeted_amount AS "Budgeted (INR):Currency:140",
			approved_amount AS "Approved (INR):Currency:140",
			variance_from_tracker AS "Variance (INR):Currency:140",
			submission_date AS "Submitted:Date:110",
			pending_approval_since AS "Pending (days):Int:110"
		FROM `tabTravel Budget Estimate`
		ORDER BY creation_date DESC
		""",
	),
	(
		"Travel Expense Report Analysis",
		"Travel Expense Report",
		["Travel Manager", "Finance Approver", "Travel Coordinator"],
		"""
		SELECT
			name AS "Expense Report:Link/Travel Expense Report:150",
			employee_name AS "Employee:Data:150",
			travel_request AS "Travel Request:Link/Travel Approval Request:150",
			submission_date AS "Submitted:Date:110",
			is_late_submission AS "Late:Check:70",
			total_expenses AS "Total Expenses:Currency:130",
			reimbursement_amount AS "Reimbursement:Currency:130",
			settlement_status AS "Settlement:Data:100",
			docstatus AS "Docstatus:Int:80"
		FROM `tabTravel Expense Report`
		ORDER BY submission_date DESC
		""",
	),
	(
		"Travel Audit Trail Report",
		"Travel Approval Request",
		["Travel Manager", "Approval Authority", "Finance Approver"],
		"""
		SELECT
			t.parent AS "Travel Request:Link/Travel Approval Request:150",
			tr.employee_name AS "Employee:Data:150",
			t.stage AS "Stage:Data:150",
			t.action AS "Action:Data:280",
			t.timestamp AS "Timestamp:Datetime:170",
			t.user AS "User:Link/User:180"
		FROM `tabTravel Request Timeline` t
		INNER JOIN `tabTravel Approval Request` tr ON tr.name = t.parent
		ORDER BY t.parent, t.timestamp
		""",
	),
]


def create_reports():
	for name, ref_doctype, roles, query in REPORTS:
		if frappe.db.exists("Report", name):
			continue

		doc = frappe.new_doc("Report")
		doc.report_name = name
		doc.ref_doctype = ref_doctype
		doc.report_type = "Query Report"
		doc.is_standard = "No"
		doc.query = query.strip()

		for role in roles:
			doc.append("roles", {"role": role})

		doc.insert(ignore_permissions=True)


# (label, function, aggregate_field, color, filters)
NUMBER_CARDS = [
	("Total Travel Requests", "Count", None, "#5e64ff", []),
	(
		"Pending Approvals",
		"Count",
		None,
		"#ffa00a",
		[
			[
				"Travel Approval Request",
				"workflow_state",
				"in",
				[
					"TA Preparation",
					"Visa Routing",
					"Visa Approved",
					"Manager Approval",
					"Fare Approval",
					"Approval Granted",
				],
			]
		],
	),
	("Total Estimated Travel Cost", "Sum", "total_estimated_cost", "#28a745", []),
	(
		"Cancelled Requests",
		"Count",
		None,
		"#ff5858",
		[["Travel Approval Request", "workflow_state", "=", "Cancelled"]],
	),
]


def create_dashboard():
	if frappe.db.exists("Dashboard", "Travel Management"):
		return

	import json

	card_names = []
	for label, function, aggregate_field, color, filters in NUMBER_CARDS:
		if frappe.db.exists("Number Card", {"label": label}):
			card_names.append(frappe.db.get_value("Number Card", {"label": label}, "name"))
			continue

		card = frappe.new_doc("Number Card")
		card.label = label
		card.document_type = "Travel Approval Request"
		card.function = function
		if aggregate_field:
			card.aggregate_function_based_on = aggregate_field
		card.color = color
		card.is_public = 1
		card.type = "Document Type"
		card.filters_json = json.dumps(filters)
		card.insert(ignore_permissions=True)
		card_names.append(card.name)

	chart_name = "Travel Requests by Stage"
	if not frappe.db.exists("Dashboard Chart", chart_name):
		chart = frappe.new_doc("Dashboard Chart")
		chart.chart_name = chart_name
		chart.chart_type = "Group By"
		chart.document_type = "Travel Approval Request"
		chart.group_by_based_on = "workflow_state"
		chart.group_by_type = "Count"
		chart.type = "Bar"
		chart.timespan = "Last Year"
		chart.time_interval = "Monthly"
		chart.is_public = 1
		chart.filters_json = json.dumps([])
		chart.insert(ignore_permissions=True)

	dashboard = frappe.new_doc("Dashboard")
	dashboard.dashboard_name = "Travel Management"
	dashboard.is_default = 0
	dashboard.append("charts", {"chart": chart_name, "width": "Full"})
	for card_name in card_names:
		dashboard.append("cards", {"card": card_name})
	dashboard.insert(ignore_permissions=True)


def bootstrap():
	create_roles()
	create_reference_master_data()
	create_workflow()
	create_email_templates()
	create_notifications()
	create_assignment_rules()
	create_reports()
	create_dashboard()
	frappe.db.commit()
	print("Travel Management setup complete.")
