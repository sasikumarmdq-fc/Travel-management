import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class TravelExpenseReport(Document):
	def validate(self):
		self.apply_business_rules()

	def before_update_after_submit(self):
		# See travel_approval_request.py for why this duplicates validate():
		# Frappe calls before_update_after_submit(), not validate(), for
		# saves on an already-submitted document.
		self.apply_business_rules()

	def on_update_after_submit(self):
		self.sync_travel_request_settlement()

	def apply_business_rules(self):
		self.calculate_totals()
		self.check_late_submission()
		self.update_settlement_status()

	def calculate_totals(self):
		total = sum(flt(row.amount) for row in self.expense_details)
		self.total_expenses = total
		self.reimbursement_amount = total
		if self.per_diem_claimed:
			self.actual_vs_per_diem = total - flt(self.per_diem_claimed)

	def check_late_submission(self):
		if self.travel_to_date and self.submission_date:
			days_elapsed = (getdate(self.submission_date) - getdate(self.travel_to_date)).days
			self.is_late_submission = 1 if days_elapsed > 3 else 0

	def update_settlement_status(self):
		if self.manager_approved and self.finance_approved and self.docstatus == 1:
			self.settlement_status = "Paid"

	def on_submit(self):
		if self.travel_request:
			frappe.db.set_value("Travel Approval Request", self.travel_request, "overall_status", "Completed")
		self.sync_travel_request_settlement()

	def sync_travel_request_settlement(self):
		""""Create Expense Report" is offered straight from "Travel Completed"
		(see travel_approval_request.js), so the parent request often never
		passes through its own "Expense Report Pending" -> "Process & Settle"
		transition at all - the Finance Approver's button to do that only
		ever appears from "Expense Report Pending", which nothing here
		reaches on its own. Once this report is genuinely fully settled
		(both approvals in, so update_settlement_status() marked it Paid),
		close the loop on the parent directly rather than leaving it stuck."""
		if not self.travel_request or self.settlement_status != "Paid":
			return

		tr_state = frappe.db.get_value("Travel Approval Request", self.travel_request, "workflow_state")
		if tr_state not in ("Travel Completed", "Expense Report Pending"):
			return

		frappe.db.set_value(
			"Travel Approval Request",
			self.travel_request,
			{
				"workflow_state": "Final Settlement",
				"overall_status": "Completed",
				"pending_action": "No pending actions",
			},
			update_modified=False,
		)

		idx = frappe.db.count(
			"Travel Request Timeline", {"parent": self.travel_request, "parenttype": "Travel Approval Request"}
		)
		frappe.get_doc(
			{
				"doctype": "Travel Request Timeline",
				"parent": self.travel_request,
				"parenttype": "Travel Approval Request",
				"parentfield": "approval_timeline",
				"idx": idx + 1,
				"stage": "Final Settlement",
				"action": f"Auto-settled: Expense Report {self.name} fully approved and paid",
				"timestamp": frappe.utils.now_datetime(),
				"user": frappe.session.user,
			}
		).insert(ignore_permissions=True)
