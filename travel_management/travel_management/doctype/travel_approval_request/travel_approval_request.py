# Copyright (c) 2026, MDQuality Apps Solutions LLP
# Travel Request controller
#
# Adapted from the "Polaris Project" travel workflow package. The original
# script assumed things that don't hold in a real Frappe install (e.g.
# writing frappe.session.user's literal first name as an email recipient,
# manually overwriting `self.name`, and a non-existent "Audit Trail"
# doctype) - those have been fixed here so the document actually saves,
# submits, and emails correctly.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate

DEFAULT_USD_TO_INR_RATE = 85
FLIGHT_APPROVAL_THRESHOLD_INR = 50000
HOTEL_APPROVAL_THRESHOLD_USD = 97
FOREX_EMERGENCY_BUFFER_USD = 500

# Ordered happy-path progression, used to derive each stage's sub-status
# (visa_status, manlio_approval_status, flight_status, hotel_status,
# insurance_status) purely from workflow_state - nothing else ever sets
# these fields, so without this they stay "Pending" forever even after the
# actual approval has happened.
HAPPY_PATH_STATES = [
	"Manager Request", "TA Preparation", "Visa Routing", "Visa Approved", "Manager Approval",
	"Approval Granted", "Manager Green Light", "Fare Approval", "Flight Booking",
	"Hotel Booking", "Hotel Approval", "Insurance Processing", "Forex Card Setup", "Ready for Travel",
	"Travel In Progress", "Travel Completed", "Expense Report Pending", "Final Settlement",
]
TERMINAL_STATES = ("Rejected", "Cancelled")


def _at_or_past(workflow_state, milestone):
	if workflow_state in TERMINAL_STATES:
		return False
	try:
		return HAPPY_PATH_STATES.index(workflow_state) >= HAPPY_PATH_STATES.index(milestone)
	except ValueError:
		return False


class TravelApprovalRequest(Document):
	# ==================== Document Lifecycle Hooks ====================

	def validate(self):
		self.apply_business_rules()

	def before_update_after_submit(self):
		# NOTE: Frappe does NOT call validate() again for saves on an
		# already-submitted document (i.e. every workflow transition after
		# the initial submit) - it calls before_update_after_submit()
		# instead. Recalculations/derived fields (costs, approval flags,
		# overall_status, pending_action) must be re-applied here too,
		# otherwise they silently go stale from the second workflow
		# transition onward.
		self.apply_business_rules()

	def apply_business_rules(self):
		self.validate_dates()
		self.validate_approvers()
		self.calculate_costs()
		self.auto_populate_insurance_details()
		self.check_approval_requirements()
		self.enforce_dual_country_visa_clearance()
		self.sync_stage_statuses()
		self.update_workflow_status()
		self.check_pending_actions()
		self.apply_stage_timestamps()

	def enforce_dual_country_visa_clearance(self):
		"""A "Both" destination has two independent visa contacts (Qatar and
		Oman), both holding the same "Visa Contact" role - the workflow's
		role check alone can't tell them apart, so either one confirming
		alone would otherwise satisfy the "Visa Contact" gate and move the
		request on before the other country's visa is actually cleared.
		Whoever just confirmed gets credited here by matching their login
		against the country they're the Approver for in Travel Reference
		Master; if the other country hasn't confirmed yet, the state is
		pulled back to "Visa Routing" so that contact still has a "Confirm
		Visa Approved" button waiting for them."""
		if self.workflow_state != "Visa Approved" or self.destination != "Both":
			return

		contact_country = frappe.db.get_value(
			"Travel Reference Master",
			{"reference_type": "Approver", "email": frappe.session.user, "status": "Active"},
			"destination",
		)
		if contact_country and "Qatar" in contact_country:
			self.qatar_visa_confirmed = 1
		if contact_country and "Oman" in contact_country:
			self.oman_visa_confirmed = 1

		if not (self.qatar_visa_confirmed and self.oman_visa_confirmed):
			self.workflow_state = "Visa Routing"
			self.visa_status = "Pending"

	def sync_stage_statuses(self):
		"""Derive each sub-status from workflow_state, since nothing else
		ever flips these fields - they are stamped the instant the workflow
		passes the milestone that makes them true, and pulled back to
		"Pending" if the document is rejected/cancelled before reaching it."""
		if self.workflow_state in TERMINAL_STATES:
			# Rejected/Cancelled can happen from many stages - leave whatever
			# sub-statuses were already stamped as-is rather than guessing.
			return

		if _at_or_past(self.workflow_state, "Manager Approval") and self.visa_status != "Approved":
			self.visa_status = "Approved"

		if _at_or_past(self.workflow_state, "Manager Green Light") and self.manlio_approval_status != "Approved":
			self.manlio_approval_status = "Approved"

		if _at_or_past(self.workflow_state, "Hotel Booking") and self.flight_status != "Confirmed":
			self.flight_status = "Confirmed"

		if _at_or_past(self.workflow_state, "Insurance Processing") and self.hotel_status != "Confirmed":
			self.hotel_status = "Confirmed"

		if _at_or_past(self.workflow_state, "Forex Card Setup") and self.insurance_status != "Confirmed":
			self.insurance_status = "Confirmed"

	def apply_stage_timestamps(self):
		"""Stamp each approval milestone once, the moment the workflow first
		reaches it - merged in from what used to be a separate Travel
		Authorization Form doctype."""
		now = frappe.utils.now_datetime()
		today = nowdate()

		ta_form_done_states = (
			"Visa Routing", "Visa Approved", "Manager Approval", "Approval Granted", "Manager Green Light",
			"Flight Booking", "Fare Approval", "Hotel Booking", "Hotel Approval",
			"Insurance Processing", "Forex Card Setup", "Ready for Travel", "Travel In Progress",
			"Travel Completed", "Expense Report Pending", "Final Settlement",
		)
		if self.workflow_state in ta_form_done_states and not self.coordinator_completion_date:
			self.coordinator_completion_date = now
			# prepared_by/prepared_date must be stamped here, not defaulted
			# at document creation - the request is usually created by the
			# Travel Manager or Employee, but the TA form is actually
			# prepared later by whichever Travel Coordinator routes it to
			# the visa contact, so the creator's login is the wrong actor.
			self.prepared_by = frappe.session.user
			self.prepared_date = today
			if self.ta_form_status == "Draft":
				self.ta_form_status = "Prepared"

		if self.visa_status == "Approved" and not self.visa_approval_date:
			self.visa_approval_date = today

		if self.manlio_approval_status == "Approved" and not self.manlio_approval_date:
			self.manlio_approval_date = today

		if self.workflow_state == "Manager Green Light" and not self.manager_green_light_date:
			self.manager_green_light_date = today

	def before_insert(self):
		self.assign_visa_contact()
		self.assign_manager()
		self.is_first_time_traveler = 1 if self.check_first_time_traveler() else 0
		if self.is_first_time_traveler:
			self.forex_card_suggested = 1
			self.forex_card_emergency_buffer = FOREX_EMERGENCY_BUFFER_USD
		# The "Employee" role's base DocPerm relies on if_owner (doc.owner),
		# but per the SOP the requesting Manager routinely creates the
		# request on the traveler's behalf - Frappe defaults owner to
		# whoever's session is doing the insert, so without this override
		# the actual traveling employee would have no read access at all to
		# their own trip whenever someone else submitted it for them.
		if self.employee:
			traveler_user = frappe.db.get_value("Employee", self.employee, "user_id")
			if traveler_user:
				self.owner = traveler_user

	def after_insert(self):
		self.add_comment("Info", _("Travel Request created for {0}").format(self.employee_name))

	def on_submit(self):
		# NOTE: on_submit runs AFTER the document is already written to the
		# database, so mutating self.<field> here is silently lost - use
		# db_set() (single field) or a direct child-doc insert() instead.
		self.db_set("overall_status", "Requested", update_modified=False)
		self.append_timeline_entry("Manager Request", "Travel request submitted")
		self.send_notification_to_manager()

	def on_update_after_submit(self):
		self.log_workflow_transition()

	def log_workflow_transition(self):
		before = self.get_doc_before_save()
		previous_state = before.workflow_state if before else None
		if previous_state != self.workflow_state:
			self.append_timeline_entry(
				self.workflow_state or "Manager Request",
				f"Moved to '{self.workflow_state}' by {frappe.session.user}",
			)

	# ==================== Validation ====================

	def validate_dates(self):
		today = getdate(nowdate())

		if self.travel_from_date and getdate(self.travel_from_date) <= today:
			frappe.throw(_("Travel From Date must be in the future"))

		if self.travel_from_date and self.travel_to_date and getdate(self.travel_to_date) <= getdate(
			self.travel_from_date
		):
			frappe.throw(_("Travel To Date must be after Travel From Date"))

		if self.hotel_checkin_date and self.hotel_checkout_date:
			if getdate(self.hotel_checkout_date) <= getdate(self.hotel_checkin_date):
				frappe.throw(_("Hotel Check-out Date must be after Check-in Date"))

		if self.insurance_start_date and self.insurance_end_date and self.travel_from_date and self.travel_to_date:
			if getdate(self.insurance_start_date) > getdate(self.travel_from_date) or getdate(
				self.insurance_end_date
			) < getdate(self.travel_to_date):
				frappe.msgprint(_("Warning: Insurance dates may not fully cover the travel period"))

	def validate_approvers(self):
		if not self.visa_contact:
			self.assign_visa_contact()
		if self.docstatus == 1 and not self.manager:
			frappe.throw(_("Reporting Manager must be assigned before submission"))

	# ==================== Assignment & Routing ====================

	def assign_visa_contact(self):
		if not self.destination:
			return

		countries = ["Qatar", "Oman"] if self.destination == "Both" else [self.destination]
		contacts = []
		for country in countries:
			reference = frappe.get_all(
				"Travel Reference Master",
				filters={"reference_type": "Approver", "destination": ["like", f"%{country}%"], "status": "Active"},
				fields=["reference_name", "email"],
				limit=1,
			)
			if reference:
				contacts.append(reference[0])

		if not contacts:
			return

		self.visa_contact = ", ".join(c.reference_name for c in contacts)
		self.visa_contact_email = ", ".join(c.email for c in contacts if c.email)
		self.visa_country = ", ".join(countries)

	def assign_manager(self):
		if self.employee and not self.manager:
			reports_to = frappe.db.get_value("Employee", self.employee, "reports_to")
			if reports_to:
				self.manager = reports_to

	@staticmethod
	def get_reference_email(name_fragment):
		"""Best-effort lookup of a contact's email from Travel Reference Master."""
		return frappe.db.get_value(
			"Travel Reference Master",
			{"reference_type": "Approver", "reference_name": ["like", f"%{name_fragment}%"]},
			"email",
		)

	def get_current_approver_role(self):
		"""Role responsible for the current workflow stage (for display only)."""
		stage_role_map = {
			"Manager Request": "Travel Manager",
			"TA Preparation": "Travel Coordinator",
			"Visa Routing": self.visa_contact or "Visa Contact",
			"Manager Approval": "Approval Authority",
			"Approval Granted": "Travel Manager",
			"Manager Green Light": "Travel Coordinator",
			"Fare Approval": "Finance Approver",
			"Flight Booking": "Travel Agent",
			"Hotel Booking": "Travel Agent",
			"Hotel Approval": "Finance Approver",
			"Insurance Processing": "Travel Coordinator",
			"Forex Card Setup": "Forex Card Processor",
			"Expense Report Pending": "Employee",
		}
		return stage_role_map.get(self.workflow_state)

	# ==================== Calculations ====================

	def calculate_costs(self):
		self.sync_usd_denominated_costs()
		self.calculate_per_diem()
		self.calculate_hotel_costs()
		self.calculate_extension_costs()
		self.calculate_total_cost()

	def sync_usd_denominated_costs(self):
		"""Flight fare and insurance cost are captured in USD (the currency
		the Polaris Finance team works in) - the INR fields are kept only
		as a derived, read-only figure for the existing INR-based approval
		threshold and cost rollup, not for direct entry."""
		rate = self.get_usd_to_inr_rate()
		if self.estimated_flight_fare_usd:
			self.estimated_flight_fare = flt(self.estimated_flight_fare_usd) * rate
		insurance_total_usd = flt(self.travel_insurance_cost_usd) + flt(self.health_insurance_cost_usd)
		if insurance_total_usd:
			self.insurance_estimated_cost = insurance_total_usd * rate

	def calculate_per_diem(self):
		if not (self.travel_from_date and self.travel_to_date and self.destination):
			return

		days = (getdate(self.travel_to_date) - getdate(self.travel_from_date)).days + 1
		self.travel_days = days

		destination = self.destination.lower()
		rate = frappe.db.get_value(
			"Travel Reference Master",
			{"reference_type": "Per Diem", "destination": ["like", f"%{self.destination}%"], "status": "Active"},
			"rate",
		)
		if not rate:
			rate = 70 if destination in ("qatar", "oman", "both") else 50

		self.per_diem_rate = rate
		self.per_diem_currency = "USD"
		self.total_per_diem = days * flt(rate)

	def calculate_hotel_costs(self):
		if self.hotel_checkin_date and self.hotel_checkout_date:
			nights = (getdate(self.hotel_checkout_date) - getdate(self.hotel_checkin_date)).days
			self.hotel_nights = nights

			if self.hotel_daily_rate_usd:
				self.total_hotel_cost_usd = nights * flt(self.hotel_daily_rate_usd)
				self.total_hotel_cost_inr = self.total_hotel_cost_usd * self.get_usd_to_inr_rate()
			elif self.hotel_daily_rate_inr:
				self.total_hotel_cost_inr = nights * flt(self.hotel_daily_rate_inr)

		if self.destination != "Both":
			return

		if self.hotel_checkin_date_2 and self.hotel_checkout_date_2:
			nights_2 = (getdate(self.hotel_checkout_date_2) - getdate(self.hotel_checkin_date_2)).days
			self.hotel_nights_2 = nights_2

			if self.hotel_daily_rate_usd_2:
				self.total_hotel_cost_usd_2 = nights_2 * flt(self.hotel_daily_rate_usd_2)
				self.total_hotel_cost_inr_2 = self.total_hotel_cost_usd_2 * self.get_usd_to_inr_rate()
			elif self.hotel_daily_rate_inr_2:
				self.total_hotel_cost_inr_2 = nights_2 * flt(self.hotel_daily_rate_inr_2)

	def calculate_extension_costs(self):
		if not (self.is_extension and self.extended_from_date and self.extended_to_date):
			return

		extension_days = (getdate(self.extended_to_date) - getdate(self.extended_from_date)).days + 1
		self.extension_per_diem = extension_days * flt(self.per_diem_rate or 70)

		extension_cost = flt(self.extended_hotel_cost) + flt(self.extension_per_diem)
		self.total_extension_cost = extension_cost

	def calculate_total_cost(self):
		# Every component here is USD-native (either a direct USD input, or
		# already computed in USD) - the total is a plain sum, no exchange
		# rate involved, so it can never drift from what was actually typed.
		total = flt(self.estimated_flight_fare_usd)
		total += flt(self.total_hotel_cost_usd)
		if self.destination == "Both":
			total += flt(self.total_hotel_cost_usd_2)
		total += flt(self.total_per_diem)
		total += flt(self.travel_insurance_cost_usd)
		total += flt(self.health_insurance_cost_usd)
		total += flt(self.forex_card_amount_loaded)
		total += flt(self.forex_misc_amount)
		self.total_estimated_cost = total

	@staticmethod
	def get_usd_to_inr_rate():
		rate = frappe.db.get_value(
			"Currency Exchange",
			{"from_currency": "USD", "to_currency": "INR"},
			"exchange_rate",
			order_by="date desc",
		)
		return flt(rate) or DEFAULT_USD_TO_INR_RATE

	# ==================== Insurance & Forex ====================

	def auto_populate_insurance_details(self):
		if not self.destination:
			return

		destination = self.destination.lower()
		insurance = frappe.get_all(
			"Travel Reference Master",
			filters={"reference_type": "Insurance", "destination": ["like", f"%{self.destination}%"], "status": "Active"},
			fields=["insurance_type", "coverage_details", "min_days"],
			limit=1,
		)

		if insurance:
			self.insurance_type = insurance[0].insurance_type
			self.insurance_notes = insurance[0].coverage_details
			self.insurance_min_days = insurance[0].min_days
		elif destination == "qatar":
			self.insurance_type = "ICICI Lombard + Qatar Mandatory Visitor Health"
			self.insurance_min_days = 30
			self.insurance_notes = "Qatar requires mandatory visitor health insurance for min 30 days"
		elif destination == "oman":
			self.insurance_type = "ICICI Lombard"
			self.insurance_notes = "Coverage aligned to exact travel dates"

		if self.travel_from_date and self.travel_to_date:
			if not self.insurance_start_date:
				self.insurance_start_date = self.travel_from_date
			if not self.insurance_end_date:
				self.insurance_end_date = self.travel_to_date

	def check_first_time_traveler(self):
		if not self.employee:
			return False
		count = frappe.db.count("Travel Approval Request", {"employee": self.employee, "docstatus": 1})
		return count == 0

	# ==================== Approval Threshold Checks ====================

	def check_approval_requirements(self):
		self.flight_approval_required = 1 if flt(self.estimated_flight_fare) >= FLIGHT_APPROVAL_THRESHOLD_INR else 0
		self.flight_approval_by = "Finance Approver" if self.flight_approval_required else ""

		if self.hotel_daily_rate_usd:
			self.hotel_approval_required = 1 if flt(self.hotel_daily_rate_usd) > HOTEL_APPROVAL_THRESHOLD_USD else 0
			self.hotel_approval_by = "Finance Approver" if self.hotel_approval_required else ""

		if self.destination == "Both" and self.hotel_daily_rate_usd_2:
			self.hotel_approval_required_2 = 1 if flt(self.hotel_daily_rate_usd_2) > HOTEL_APPROVAL_THRESHOLD_USD else 0
			self.hotel_approval_by_2 = "Finance Approver" if self.hotel_approval_required_2 else ""

	# ==================== Workflow Status ====================

	def update_workflow_status(self):
		sub_statuses = [
			self.ta_form_status,
			self.visa_status,
			self.manlio_approval_status,
			self.flight_status,
			self.hotel_status,
			self.insurance_status,
		]

		if any(status == "Rejected" for status in sub_statuses):
			self.overall_status = "Rejected"
		elif self.workflow_state in ("Travel Completed", "Expense Report Pending", "Final Settlement"):
			self.overall_status = "Completed"
		elif self.workflow_state == "Cancelled":
			self.overall_status = "Cancelled"
		elif self.workflow_state in ("Ready for Travel", "Travel In Progress"):
			self.overall_status = "Approved"
		elif self.docstatus == 1:
			self.overall_status = "In Progress"

	def check_pending_actions(self):
		pending = []
		state = self.workflow_state

		if state in (None, "", "Draft"):
			pending.append("Employee/Travel Manager to submit the request")
		elif state == "Manager Request":
			pending.append("Travel Manager to confirm and route to TA Form")
		elif state == "TA Preparation":
			if not self.estimated_flight_fare:
				pending.append("Travel Coordinator to estimate flight fare before routing to visa contact")
			else:
				pending.append(f"Route to {self.visa_contact or 'visa contact'} for visa processing")
		elif state == "Visa Routing" and self.destination == "Both":
			countries = [c.strip() for c in (self.visa_country or "").split(",")]
			contacts = [c.strip() for c in (self.visa_contact or "").split(",")]
			confirmed = {"Qatar": self.qatar_visa_confirmed, "Oman": self.oman_visa_confirmed}
			outstanding = [
				f"{country} ({contact})"
				for country, contact in zip(countries, contacts)
				if not confirmed.get(country)
			]
			pending.append(f"Awaiting visa confirmation from: {', '.join(outstanding)}")
		elif state in ("Visa Routing", "Visa Approved"):
			pending.append("Visa approval / routing to final approver")
		elif state == "Manager Approval":
			pending.append("Approval Authority to review and approve")
		elif state == "Approval Granted":
			pending.append("Travel Manager to confirm green light and proceed with bookings")
		elif state == "Manager Green Light":
			pending.append("Travel Coordinator to route to fare approval or flight booking")
		elif state == "Fare Approval":
			pending.append("Finance Approver to review high-value fare")
		elif state == "Flight Booking":
			pending.append("Travel Agent to issue tickets and move to hotel booking")
		elif state == "Hotel Booking" and self.destination == "Both":
			if not (self.hotel_daily_rate_usd and self.hotel_daily_rate_usd_2):
				pending.append("Travel Agent to book hotels for both Qatar and Oman")
			elif self.hotel_approval_required or self.hotel_approval_required_2:
				pending.append("Travel Agent to route above-threshold hotel(s) for Finance Approver sign-off")
			else:
				pending.append("Travel Agent to confirm hotels and move to insurance")
		elif state == "Hotel Booking":
			pending.append(
				"Travel Agent to route above-threshold hotel for Finance Approver sign-off"
				if self.hotel_approval_required
				else "Travel Agent to confirm hotel and move to insurance"
			)
		elif state == "Hotel Approval":
			legs = []
			if self.hotel_approval_required:
				legs.append("Qatar" if self.destination == "Both" else self.destination)
			if self.destination == "Both" and self.hotel_approval_required_2:
				legs.append("Oman")
			suffix = f" ({', '.join(legs)})" if self.destination == "Both" and legs else ""
			pending.append(f"Hotel approval from {self.hotel_approval_by or self.hotel_approval_by_2 or 'Finance Approver'}{suffix}")
		elif state == "Insurance Processing":
			pending.append("Travel Coordinator to arrange insurance")
		elif state == "Forex Card Setup":
			pending.append("Forex Card Processor to activate card")
		elif state == "Expense Report Pending":
			pending.append("Employee to submit expense report")

		self.pending_action = ", ".join(pending) if pending else "No pending actions"

	# ==================== Notifications ====================

	def send_notification_to_manager(self):
		if not self.manager:
			return
		manager_user = frappe.db.get_value("Employee", self.manager, "user_id")
		if not manager_user:
			return

		subject = f"Action Required: Travel Request {self.name} - Await TA Form Preparation"
		message = f"""
		<p>Travel request created for {self.employee_name}</p>
		<ul>
			<li>Destination: {self.destination}</li>
			<li>Travel Dates: {self.travel_from_date} to {self.travel_to_date}</li>
			<li>Purpose: {self.trip_purpose or ''}</li>
			<li>Estimated Cost: USD {flt(self.total_estimated_cost):,.2f}</li>
		</ul>
		<p><a href="/app/travel-request/{self.name}">View Request</a></p>
		"""
		self.send_email(manager_user, subject, message)

	@staticmethod
	def send_email(recipient, subject, message, cc=None):
		if not recipient:
			return
		try:
			frappe.sendmail(
				recipients=[recipient],
				subject=subject,
				message=message,
				cc=[c for c in (cc or []) if c],
				reference_doctype="Travel Approval Request",
			)
		except Exception:
			frappe.log_error(title="Travel Request email failed")

	# ==================== Timeline ====================

	def append_timeline_entry(self, stage, action):
		"""Insert a timeline row directly rather than self.append(), since
		this is called from hooks (on_submit, on_update_after_submit) that
		run after the parent document has already been written - an
		in-memory append() there would be silently discarded.
		"""
		idx = frappe.db.count("Travel Request Timeline", {"parent": self.name, "parenttype": self.doctype})
		frappe.get_doc(
			{
				"doctype": "Travel Request Timeline",
				"parent": self.name,
				"parenttype": self.doctype,
				"parentfield": "approval_timeline",
				"idx": idx + 1,
				"stage": stage,
				"action": action,
				"timestamp": frappe.utils.now_datetime(),
				"user": frappe.session.user,
			}
		).insert(ignore_permissions=True)

	# ==================== Custom Actions (called from client script) ====================

	@frappe.whitelist()
	def confirm_travel_approval(self):
		self.manager_green_light_date = nowdate()
		self.manlio_approval_status = "Approved"
		self.manlio_approval_date = nowdate()
		self.append_timeline_entry("Approval Granted", "Approved by final approving authority")
		self.save()
		return self.as_dict()


# ==================== Whitelisted API Methods ====================


@frappe.whitelist()
def get_hotel_options(destination):
	return frappe.get_all(
		"Travel Reference Master",
		filters={"reference_type": "Hotel", "city": destination, "status": "Active"},
		fields=["name", "reference_name as hotel_name", "local_rate", "usd_rate", "inr_rate"],
	)


@frappe.whitelist()
def get_per_diem_rate(destination):
	rate = frappe.db.get_value(
		"Travel Reference Master",
		{"reference_type": "Per Diem", "destination": ["like", f"%{destination}%"], "status": "Active"},
		"rate",
	)
	return rate or 70


@frappe.whitelist()
def get_insurance_requirements(destination):
	records = frappe.get_all(
		"Travel Reference Master",
		filters={"reference_type": "Insurance", "destination": ["like", f"%{destination}%"], "status": "Active"},
		fields=["name", "insurance_type", "provider", "coverage_details", "min_days", "max_days"],
		limit=1,
	)
	return records[0] if records else {}


@frappe.whitelist()
def create_expense_report(travel_request_id):
	if not frappe.db.exists("DocType", "Travel Expense Report"):
		frappe.throw(_("Travel Expense Report is not yet configured on this site."))

	tr = frappe.get_doc("Travel Approval Request", travel_request_id)
	if tr.docstatus != 1:
		frappe.throw(_("Travel Request must be submitted first"))

	expense_report = frappe.get_doc(
		{
			"doctype": "Travel Expense Report",
			"travel_request": travel_request_id,
			"employee": tr.employee,
			"submission_date": nowdate(),
		}
	).insert()

	return expense_report


# ==================== Scheduled Tasks (see hooks.py: scheduler_events) ====================


def send_approval_reminders():
	"""Daily: nudge whoever holds an in-progress request pending > 1 day."""
	pending_states = ("Manager Approval", "Approval Granted", "Manager Green Light", "Fare Approval", "Flight Booking", "Hotel Booking", "Hotel Approval")
	pending_requests = frappe.get_all(
		"Travel Approval Request",
		filters={
			"docstatus": 1,
			"workflow_state": ["in", pending_states],
			"modified": ["<", frappe.utils.add_to_date(None, days=-1)],
		},
		fields=["name", "workflow_state"],
	)

	for request in pending_requests:
		tr = frappe.get_doc("Travel Approval Request", request.name)
		role = tr.get_current_approver_role()
		if not role:
			continue
		subject = f"Reminder: Travel Request {tr.name} Pending Your Approval"
		message = f"<p>Travel Request {tr.name} has been pending in stage '{tr.workflow_state}' for more than 1 business day.</p>"
		for user in frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"):
			tr.send_email(user, subject, message)


def send_expense_report_reminders():
	"""Daily: remind employees to submit expense reports within 3 working days of travel end."""
	if not frappe.db.exists("DocType", "Travel Expense Report"):
		return

	completed_travels = frappe.get_all(
		"Travel Approval Request",
		filters={"docstatus": 1, "workflow_state": "Expense Report Pending"},
		fields=["name", "employee", "travel_to_date"],
	)

	for travel in completed_travels:
		if frappe.db.exists("Travel Expense Report", {"travel_request": travel.name}):
			continue

		days_since = (getdate(nowdate()) - getdate(travel.travel_to_date)).days
		if 0 <= days_since <= 3:
			employee_user = frappe.db.get_value("Employee", travel.employee, "user_id")
			if not employee_user:
				continue
			subject = f"Reminder: Submit Expense Report for Travel {travel.name}"
			message = f"<p>Please submit your expense report for travel {travel.name} within 3 working days of completing the trip.</p><p>Days remaining: {3 - days_since}</p>"
			frappe.sendmail(
				recipients=[employee_user],
				subject=subject,
				message=message,
				reference_doctype="Travel Approval Request",
				reference_name=travel.name,
			)
