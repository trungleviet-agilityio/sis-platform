# Credit: adapted from ship-it-safely infra/terraform/bootstrap/budget.tf (lab ADR 0002, B21).
# T7 (WA20): the budget comes from the plan (M6 budget_monthly_usd; each account gets the project ceiling). Actual and
# forecast alerts at 80 and 100 percent go to the notify topic, whose email subscription the owner confirms once.
# account_id is omitted on purpose: it defaults to the caller's account.

locals {
  budget_alerts = {
    actual_80      = { type = "ACTUAL", threshold = 80 }
    actual_100     = { type = "ACTUAL", threshold = 100 }
    forecasted_80  = { type = "FORECASTED", threshold = 80 }
    forecasted_100 = { type = "FORECASTED", threshold = 100 }
  }
}

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly-cost"
  budget_type  = "COST"
  limit_amount = tostring(var.platform.budget_monthly_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = local.budget_alerts

    content {
      comparison_operator       = "GREATER_THAN"
      threshold                 = notification.value.threshold
      threshold_type            = "PERCENTAGE"
      notification_type         = notification.value.type
      subscriber_sns_topic_arns = [aws_sns_topic.notify.arn]
    }
  }

  depends_on = [aws_sns_topic_policy.notify]
}

# Cost Anomaly Detection is free. The monitor watches spend per AWS service; the subscription alerts the notify
# topic at once when the total impact reaches 10 percent of the monthly budget (at least 1 USD).
resource "aws_ce_anomaly_monitor" "services" {
  count = var.create_anomaly_monitor ? 1 : 0

  name              = "${local.name}-services"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "notify" {
  count = var.create_anomaly_monitor ? 1 : 0

  name             = "${local.name}-anomalies"
  frequency        = "IMMEDIATE"
  monitor_arn_list = [aws_ce_anomaly_monitor.services[0].arn]

  subscriber {
    type    = "SNS"
    address = aws_sns_topic.notify.arn
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(max(1, ceil(var.platform.budget_monthly_usd * 0.1)))]
    }
  }

  depends_on = [aws_sns_topic_policy.notify]
}
