output "resource_group_name" {
  value = module.resource_group.name
}

output "acr_login_server" {
  value = module.acr.login_server
  # The pipeline reads this to know where to push images:
  # docker push <acr_login_server>/backend:<git-sha>
}
