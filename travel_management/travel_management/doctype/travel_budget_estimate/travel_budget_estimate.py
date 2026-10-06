import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class TravelBudgetEstimate(Document):
	def before_insert(self):
		if not self.created_by_user:
			self.created_by_user = frappe.session.user
		if not self.creation_date:
			self.creation_date = nowdate()

	def validate(self):
		self.calculate_totals()
		self.calculate_pending_days()
		self.set_status_message()

	def calculate_totals(self):
		for row in self.budget_details:
			row.total_cost = (
				flt(row.estimated_flight_cost)
				+ flt(row.estimated_hotel_cost)
				+ flt(row.per_diem)
				+ flt(row.insurance)
				+ flt(row.other_costs)
			)

		total = sum(flt(row.total_cost) for row in self.budget_details)
		self.total_amount = total
		self.total_budgeted_amount = total

		if self.approved_amount:
			self.variance_from_tracker = flt(self.total_amount) - flt(self.approved_amount)

	def calculate_pending_days(self):
		if self.status == "Submitted" and self.submission_date:
			self.pending_approval_since = (getdate(nowdate()) - getdate(self.submission_date)).days
		else:
			self.pending_approval_since = 0

	def set_status_message(self):
		messages = {
			"Draft": "Awaiting submission",
			"Submitted": f"Pending approval ({self.pending_approval_since or 0} day(s))",
			"Approved": "Budget approved",
			"Rejected": "Budget rejected - see comments",
		}
		self.status_message = messages.get(self.status, "")
