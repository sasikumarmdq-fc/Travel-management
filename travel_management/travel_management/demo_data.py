# Copyright (c) 2026, MDQuality Apps Solutions LLP
"""Sample personas and sample Travel Approval Request transactions.

Run with:
    bench --site <site> execute travel_management.travel_management.demo_data.run

Requires travel_management.travel_management.setup.bootstrap to have already
run (roles, reference master data, workflow). Also requires at least one
Company to exist (i.e. the ERPNext setup wizard has been completed).

Safe to re-run - personas are looked up by email before being created, and
sample requests are looked up by a fixed docname pattern.
"""

import frappe
from frappe.utils import add_days, nowdate

# (key, first_name, last_name, email, custom_role, reports_to_key)
# NOTE: the dict key in column 1 (e.g. "asha") is only an internal code
# identifier - it is not shown anywhere. Names in columns 2/3 match the
# people named in the source SOP documents (Asha, Sunil, Sadiq, Manlio,
# Alberto, Peter, Krishna) exactly, as single first names with no surname,
# same as the SOP itself. Priya/Rahul/Meera/Fatima are not named in the SOP
# (it only says "Manager"/"Employee"/"Travel Agent" generically there), so
# there is nothing to revert them to - they stay as-is.
PERSONAS = [
	("priya", "Priya", "Nair", "priya.nair@example.com", "Travel Manager", None),
	("rahul", "Rahul", "Sharma", "rahul.sharma@example.com", "Employee", "priya"),
	("meera", "Meera", "Singh", "meera.singh@example.com", "Employee", "priya"),
	("asha", "Asha", "", "asha@example.com", "Travel Coordinator", "priya"),
	("sunil", "Sunil", "", "sunil@example.com", "Visa Contact", "priya"),
	("sadiq", "Sadiq", "", "sadiq@example.com", "Visa Contact", "priya"),
	("manlio", "Manlio", "", "manlio@example.com", "Approval Authority", "priya"),
	("alberto", "Alberto", "", "alberto@example.com", "Finance Approver", "priya"),
	("peter", "Peter", "", "peter@example.com", "Finance Approver", "priya"),
	("fatima", "Fatima", "Khan", "travelagent@example.com", "Travel Agent", "priya"),
	("krishna", "Krishna", "", "krishna@example.com", "Forex Card Processor", "priya"),
]


def get_company():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	return company or frappe.get_all("Company", pluck="name")[0]


def create_personas():
	"""Create a User + Employee for each persona, idempotent by email."""
	company = get_company()
	employees = {}

	for key, first_name, last_name, email, role, reports_to_key in PERSONAS:
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": first_name,
					"last_name": last_name,
					"send_welcome_email": 0,
					"user_type": "System User",
					"new_password": "Mdqapps@2026",
				}
			)
			user.append_roles(role, "Employee")
			user.insert(ignore_permissions=True)
		else:
			user = frappe.get_doc("User", email)
			user.append_roles(role, "Employee")
			user.save(ignore_permissions=True)

		existing = frappe.db.get_value("Employee", {"user_id": email}, "name")
		if existing:
			employees[key] = existing
			continue

		emp = frappe.new_doc("Employee")
		emp.naming_series = "HR-EMP-"
		emp.first_name = first_name
		emp.last_name = last_name
		emp.employee_name = f"{first_name} {last_name}".strip()
		emp.gender = "Female" if first_name in ("Priya", "Meera", "Asha", "Fatima") else "Male"
		emp.date_of_birth = add_days(nowdate(), -365 * 30)
		emp.date_of_joining = add_days(nowdate(), -365)
		emp.company = company
		emp.user_id = email
		emp.status = "Active"
		if reports_to_key and reports_to_key in employees:
			emp.reports_to = employees[reports_to_key]
		emp.insert(ignore_permissions=True)
		employees[key] = emp.name

	frappe.db.commit()
	return employees


def _as(user, fn):
	"""Run fn() as the given user, always restoring the previous session user."""
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user(previous)


def _transition(doc, action, user):
	from frappe.model.workflow import apply_workflow

	def go():
		fresh = frappe.get_doc(doc.doctype, doc.name)
		return apply_workflow(fresh, action)

	return _as(user, go)


def _set_fields(name, user, **fields):
	"""Simulate a user filling in operational fields on the form and saving -
	e.g. Krishna recording the forex card number once it's issued."""

	def go():
		doc = frappe.get_doc("Travel Approval Request", name)
		for k, v in fields.items():
			doc.set(k, v)
		doc.save()

	return _as(user, go)


def _new_request(employee_key, employee_id, destination, **fields):
	email = dict((p[0], p[3]) for p in PERSONAS)[employee_key]

	def create():
		doc = frappe.new_doc("Travel Approval Request")
		doc.employee = employee_id
		doc.destination = destination
		doc.trip_purpose = fields.pop("trip_purpose", "Client meeting")
		for k, v in fields.items():
			doc.set(k, v)
		doc.insert()
		return doc.name

	return _as(email, create)


EMAIL = dict((p[0], p[3]) for p in PERSONAS)


def create_sample_requests():
	emp = {
		key: frappe.db.get_value("Employee", {"user_id": email}, "name")
		for key, _f, _l, email, _r, _rt in PERSONAS
	}

	created = {}

	# --- Scenario 1: Basic end-to-end flow, walked all the way to Final Settlement.
	# Also covers the first-time-traveler/forex-card branch, since this is
	# genuinely Rahul's first submitted request. ---
	name = _new_request(
		"rahul",
		emp["rahul"],
		"Qatar",
		trip_purpose="Client workshop in Doha",
		travel_from_date=add_days(nowdate(), 15),
		travel_to_date=add_days(nowdate(), 18),
		hotel_checkin_date=add_days(nowdate(), 15),
		hotel_checkout_date=add_days(nowdate(), 18),
		estimated_flight_fare_usd=375,
	)
	created["scenario_1_basic_flow"] = name
	doc = frappe.get_doc("Travel Approval Request", name)
	_transition(doc, "Submit Travel Request", EMAIL["rahul"])
	_transition(doc, "Confirm & Request TA Form", EMAIL["priya"])
	_transition(doc, "Complete & Route to Visa Contact", EMAIL["asha"])
	_transition(doc, "Confirm Visa Approved", EMAIL["sunil"])
	_transition(doc, "Route to Manlio Approval", EMAIL["sunil"])
	_transition(doc, "Approve Travel", EMAIL["manlio"])
	_transition(doc, "Confirm Green Light & Proceed", EMAIL["priya"])
	_transition(doc, "Proceed to Flight Booking", EMAIL["asha"])
	_transition(doc, "Issue Tickets & Move to Hotel", EMAIL["fatima"])
	_transition(doc, "Confirm Hotel & Move to Insurance", EMAIL["fatima"])
	# This is Rahul's very first submitted request, so before_insert() correctly
	# flagged is_first_time_traveler=1 - this also doubles as the "first-time
	# traveler with forex card" scenario (Implementation Plan Test Case 6).
	_transition(doc, "Complete Insurance & Setup Forex", EMAIL["asha"])
	_set_fields(
		name,
		EMAIL["krishna"],
		forex_card_status="Activated",
		forex_card_issued=1,
		forex_card_number="XXXX-XXXX-4471",
		forex_card_amount_loaded=500,
	)
	_transition(doc, "Activate Card & Complete Setup", EMAIL["krishna"])
	_transition(doc, "Mark as Travel Started", EMAIL["rahul"])
	_transition(doc, "Mark Travel Complete", EMAIL["rahul"])
	_transition(doc, "Awaiting Expense Report", EMAIL["rahul"])
	_transition(doc, "Process & Settle", EMAIL["alberto"])

	# --- Scenario 2: High-value flight fare (>= INR 50,000) routes through Fare Approval ---
	name = _new_request(
		"rahul",
		emp["rahul"],
		"Qatar",
		trip_purpose="Annual partner summit",
		travel_from_date=add_days(nowdate(), 20),
		travel_to_date=add_days(nowdate(), 23),
		estimated_flight_fare_usd=800,
	)
	created["scenario_2_high_value_fare"] = name
	doc = frappe.get_doc("Travel Approval Request", name)
	_transition(doc, "Submit Travel Request", EMAIL["rahul"])
	_transition(doc, "Confirm & Request TA Form", EMAIL["priya"])
	_transition(doc, "Complete & Route to Visa Contact", EMAIL["asha"])
	_transition(doc, "Confirm Visa Approved", EMAIL["sunil"])
	_transition(doc, "Route to Manlio Approval", EMAIL["sunil"])
	_transition(doc, "Approve Travel", EMAIL["manlio"])
	_transition(doc, "Confirm Green Light & Proceed", EMAIL["priya"])
	_transition(doc, "Route to Fare Approval", EMAIL["asha"])  # condition: fare >= 50000
	_transition(doc, "Approve Fare & Proceed", EMAIL["alberto"])
	_transition(doc, "Issue Tickets & Move to Hotel", EMAIL["fatima"])

	# --- Scenario 3: Below-threshold hotel rate (< USD 97) requires Finance approval ---
	name = _new_request(
		"meera",
		emp["meera"],
		"Oman",
		trip_purpose="Vendor site visit",
		travel_from_date=add_days(nowdate(), 12),
		travel_to_date=add_days(nowdate(), 14),
		hotel_checkin_date=add_days(nowdate(), 12),
		hotel_checkout_date=add_days(nowdate(), 14),
		hotel_daily_rate_usd=60.75,
		estimated_flight_fare_usd=295,
	)
	created["scenario_3_budget_hotel_approval"] = name
	doc = frappe.get_doc("Travel Approval Request", name)
	_transition(doc, "Submit Travel Request", EMAIL["meera"])
	_transition(doc, "Confirm & Request TA Form", EMAIL["priya"])
	_transition(doc, "Complete & Route to Visa Contact", EMAIL["asha"])
	_transition(doc, "Confirm Visa Approved", EMAIL["sadiq"])
	_transition(doc, "Route to Manlio Approval", EMAIL["sadiq"])
	_transition(doc, "Approve Travel", EMAIL["manlio"])
	_transition(doc, "Confirm Green Light & Proceed", EMAIL["priya"])
	_transition(doc, "Proceed to Flight Booking", EMAIL["asha"])
	_transition(doc, "Issue Tickets & Move to Hotel", EMAIL["fatima"])
	_transition(doc, "Route to Hotel Approval", EMAIL["fatima"])  # condition: usd < 97
	_transition(doc, "Approve Hotel & Proceed", EMAIL["alberto"])

	# --- Scenario 4: Travel extension, linked back to the original request ---
	name = _new_request(
		"rahul",
		emp["rahul"],
		"Qatar",
		trip_purpose="Extension of client workshop",
		travel_from_date=add_days(nowdate(), 15),
		travel_to_date=add_days(nowdate(), 18),
		is_extension=1,
		original_travel_request=created["scenario_1_basic_flow"],
		extended_from_date=add_days(nowdate(), 19),
		extended_to_date=add_days(nowdate(), 21),
	)
	created["scenario_4_extension"] = name

	# --- Scenario 6: Repeat traveler -> insurance completes WITHOUT the forex
	# card branch (Meera's scenario_3 request above already used up her
	# "first-time traveler" status, so before_insert() correctly sets
	# is_first_time_traveler=0 here - this exercises the complementary
	# branch to scenario_1's first-time/forex-card path). ---
	name = _new_request(
		"meera",
		emp["meera"],
		"Oman",
		trip_purpose="Follow-up vendor review",
		travel_from_date=add_days(nowdate(), 25),
		travel_to_date=add_days(nowdate(), 28),
		estimated_flight_fare_usd=260,
	)
	created["scenario_6_repeat_traveler_no_forex"] = name
	doc = frappe.get_doc("Travel Approval Request", name)
	_transition(doc, "Submit Travel Request", EMAIL["meera"])
	_transition(doc, "Confirm & Request TA Form", EMAIL["priya"])
	_transition(doc, "Complete & Route to Visa Contact", EMAIL["asha"])
	_transition(doc, "Confirm Visa Approved", EMAIL["sadiq"])
	_transition(doc, "Route to Manlio Approval", EMAIL["sadiq"])
	_transition(doc, "Approve Travel", EMAIL["manlio"])
	_transition(doc, "Confirm Green Light & Proceed", EMAIL["priya"])
	_transition(doc, "Proceed to Flight Booking", EMAIL["asha"])
	_transition(doc, "Issue Tickets & Move to Hotel", EMAIL["fatima"])
	_transition(doc, "Confirm Hotel & Move to Insurance", EMAIL["fatima"])
	_transition(doc, "Complete Insurance", EMAIL["asha"])  # condition: not a first-time traveler

	# --- Scenario 7: Multi-destination travel (both Qatar and Oman) ---
	name = _new_request(
		"rahul",
		emp["rahul"],
		"Both",
		trip_purpose="Regional roadshow - Doha and Muscat",
		travel_from_date=add_days(nowdate(), 30),
		travel_to_date=add_days(nowdate(), 34),
	)
	created["scenario_7_multi_destination"] = name
	doc = frappe.get_doc("Travel Approval Request", name)
	_transition(doc, "Submit Travel Request", EMAIL["rahul"])
	_transition(doc, "Confirm & Request TA Form", EMAIL["priya"])

	# --- Scenario 9: Cancellation mid-flow ---
	name = _new_request(
		"rahul",
		emp["rahul"],
		"Qatar",
		trip_purpose="Trade show (cancelled after approval)",
		travel_from_date=add_days(nowdate(), 40),
		travel_to_date=add_days(nowdate(), 42),
	)
	created["scenario_9_cancellation"] = name
	doc = frappe.get_doc("Travel Approval Request", name)
	_transition(doc, "Submit Travel Request", EMAIL["rahul"])
	_transition(doc, "Confirm & Request TA Form", EMAIL["priya"])
	_transition(doc, "Cancel Travel", EMAIL["priya"])

	frappe.db.commit()
	return created


def create_supporting_documents(created):
	"""Sample Travel Budget Estimate and Travel Expense Report records,
	linked to the sample Travel Approval Requests. The TA Form fields now
	live directly on Travel Approval Request itself (role-gated by
	permlevel), so there's nothing separate to create for it here."""
	result = {}

	def fill_ta_form_fields():
		doc = frappe.get_doc("Travel Approval Request", created["scenario_1_basic_flow"])
		doc.business_justification = "Kick-off for the Q4 partner engagement"
		doc.visa_required = 1
		doc.visa_type = "Business Visa"
		doc.save()

	_as(EMAIL["asha"], fill_ta_form_fields)

	# --- Travel Budget Estimate covering two of the sample requests ---
	def make_budget_estimate():
		doc = frappe.new_doc("Travel Budget Estimate")
		doc.period = "Q4 2026"
		doc.status = "Submitted"
		doc.submitted_by = EMAIL["priya"]
		doc.submission_date = nowdate()
		for scenario_key in ("scenario_1_basic_flow", "scenario_2_high_value_fare"):
			tr = frappe.get_doc("Travel Approval Request", created[scenario_key])
			doc.append(
				"budget_details",
				{
					"travel_request": tr.name,
					"estimated_flight_cost": tr.estimated_flight_fare,
					"estimated_hotel_cost": tr.total_hotel_cost_inr,
					"per_diem": (tr.total_per_diem or 0) * 85,
					"insurance": tr.insurance_estimated_cost,
				},
			)
		doc.insert()
		return doc.name

	result["budget_estimate"] = _as(EMAIL["asha"], make_budget_estimate)

	def approve_budget_estimate():
		doc = frappe.get_doc("Travel Budget Estimate", result["budget_estimate"])
		doc.status = "Approved"
		doc.asha_approval_date = nowdate()
		doc.peter_review_date = nowdate()
		doc.final_approval_date = nowdate()
		doc.approved_amount = doc.total_amount
		doc.approval_comments = "Within quarterly travel budget - approved."
		doc.save()

	_as(EMAIL["alberto"], approve_budget_estimate)

	# --- Travel Expense Report for the completed basic-flow request ---
	def make_expense_report():
		tr = frappe.get_doc("Travel Approval Request", created["scenario_1_basic_flow"])
		doc = frappe.new_doc("Travel Expense Report")
		doc.travel_request = tr.name
		doc.employee = tr.employee
		doc.submission_date = add_days(tr.travel_to_date, 2)
		doc.append(
			"expense_details",
			{"category": "Flight", "description": "Doha round-trip", "amount": tr.estimated_flight_fare},
		)
		doc.append(
			"expense_details",
			{"category": "Hotel", "description": "3 nights, Doubletree Doha", "amount": tr.total_hotel_cost_inr},
		)
		doc.append(
			"expense_details",
			{"category": "Food", "description": "Meals not covered by per diem", "amount": 3500},
		)
		doc.insert()
		return doc.name

	result["expense_report"] = _as(EMAIL["rahul"], make_expense_report)

	def submit_expense_report():
		doc = frappe.get_doc("Travel Expense Report", result["expense_report"])
		doc.submit()

	_as(EMAIL["rahul"], submit_expense_report)

	def approve_expense_report():
		doc = frappe.get_doc("Travel Expense Report", result["expense_report"])
		doc.manager_approved = 1
		doc.save()

	_as(EMAIL["priya"], approve_expense_report)

	def settle_expense_report():
		doc = frappe.get_doc("Travel Expense Report", result["expense_report"])
		doc.finance_approved = 1
		doc.save()

	_as(EMAIL["alberto"], settle_expense_report)

	frappe.db.commit()
	return result


SCENARIO_DOCNAMES = {
	"scenario_1_basic_flow": "TR-2026-00001",
	"scenario_2_high_value_fare": "TR-2026-00002",
	"scenario_3_budget_hotel_approval": "TR-2026-00003",
	"scenario_4_extension": "TR-2026-00004",
	"scenario_6_repeat_traveler_no_forex": "TR-2026-00005",
	"scenario_7_multi_destination": "TR-2026-00006",
	"scenario_9_cancellation": "TR-2026-00007",
}


def run_supporting_only():
	"""Create just the TA Form / Budget Estimate / Expense Report samples
	against the Travel Approval Requests already created by a prior run() -
	use this instead of run() to avoid duplicating the 7 sample requests."""
	create_personas()
	supporting = create_supporting_documents(SCENARIO_DOCNAMES)
	print("Supporting documents created:")
	for kind, name in supporting.items():
		print(f"  {kind}: {name}")


def run():
	create_personas()
	created = create_sample_requests()
	supporting = create_supporting_documents(created)
	print("Sample personas and transactions created:")
	for scenario, name in created.items():
		state = frappe.db.get_value("Travel Approval Request", name, "workflow_state")
		print(f"  {scenario}: {name}  [workflow_state={state}]")
	print("Supporting documents created:")
	for kind, name in supporting.items():
		print(f"  {kind}: {name}")
