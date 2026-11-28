resource "aws_dynamodb_table" "transactions" {
  name         = "${var.project_name}-transactions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "transaction_id"

  attribute {
    name = "transaction_id"
    type = "S"
  }

  attribute {
    name = "record_type"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  attribute {
    name = "customer_hash"
    type = "S"
  }

  global_secondary_index {
    name            = "customer-history-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "customer_hash"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "recent-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "record_type"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = local.common_tags
}
