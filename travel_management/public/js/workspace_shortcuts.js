// Renders the Travel Management workspace shortcut cards as square tiles with an icon.
// Scoped by `link_to` doctype so it only affects the five Travel Management shortcuts
// and leaves every other workspace's shortcuts untouched.
frappe.provide("travel_management");

travel_management.WORKSPACE_SHORTCUT_ICONS = {
	"Travel Approval Request": "es-line-check",
	"Travel Budget Estimate": "icon-money-coins-1",
	"Travel Expense Report": "icon-expenses",
	"Travel Reference Master": "es-line-book",
};

travel_management.patch_shortcut_widget = function () {
	const ShortcutWidget = frappe.widget && frappe.widget.widget_factory && frappe.widget.widget_factory.shortcut;
	if (!ShortcutWidget || ShortcutWidget.__travel_management_patched) return;

	const original_set_title = ShortcutWidget.prototype.set_title;
	ShortcutWidget.prototype.set_title = function (...args) {
		original_set_title.apply(this, args);

		const icon_name = travel_management.WORKSPACE_SHORTCUT_ICONS[this.link_to];
		if (!icon_name) return;

		this.widget.addClass("travel-square-shortcut");
		if (!this.title_field.find(".travel-shortcut-icon").length) {
			this.title_field.prepend(
				`<div class="travel-shortcut-icon">${frappe.utils.icon(icon_name, "lg")}</div>`
			);
		}
	};

	ShortcutWidget.__travel_management_patched = true;
};

travel_management.patch_shortcut_widget();
frappe.router && frappe.router.on && frappe.router.on("change", travel_management.patch_shortcut_widget);
