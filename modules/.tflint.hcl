# tflint config for modules/ (ADR 0002, H9). Offline: only the bundled terraform ruleset. The AWS ruleset is a
# downloaded plugin, so it is left out until the build can fetch it in CI.
config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}
