# ActuNode Cloud on Hetzner (D-61): one server for the beta, a separate volume for all data, a firewall.
# DNS records are printed as outputs and created by hand (docs/HOSTED_DEPLOY.md).
terraform {
  required_version = ">= 1.9"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.70"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

variable "hcloud_token" {
  description = "Hetzner Cloud API token (read/write), from the project's Security page"
  type        = string
  sensitive   = true
}

variable "ssh_public_key" {
  description = "Your SSH public key (the server accepts only key logins)"
  type        = string
}

variable "admin_cidrs" {
  description = "Addresses allowed to reach SSH, e.g. [\"203.0.113.7/32\"]"
  type        = list(string)
}

variable "location" {
  description = "nbg1 / fsn1 (Germany) or hel1 (Finland); EU first (D-61)"
  type        = string
  default     = "nbg1"
}

variable "server_type" {
  description = "8 vCPU, 16 GB to start; resize later"
  type        = string
  default     = "cpx41"
}

variable "domain" {
  type    = string
  default = "actunode.com"
}

variable "release" {
  description = "The ActuNode release (git tag) to deploy; it must include the hosted service (v0.4.0 or later)"
  type        = string
  default     = "v0.4.0"
}

variable "volume_gb" {
  type    = number
  default = 50
}

resource "hcloud_ssh_key" "admin" {
  name       = "actunode-admin"
  public_key = var.ssh_public_key
}

resource "hcloud_firewall" "edge" {
  name = "actunode-edge"
  rule {
    description = "SSH from the admin addresses only"
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = var.admin_cidrs
  }
  dynamic "rule" {
    for_each = { "80" = "HTTP (redirects to HTTPS)", "443" = "HTTPS", "8883" = "MQTT over TLS (robots)" }
    content {
      description = rule.value
      direction   = "in"
      protocol    = "tcp"
      port        = rule.key
      source_ips  = ["0.0.0.0/0", "::/0"]
    }
  }
  rule {
    description = "Ping"
    direction   = "in"
    protocol    = "icmp"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_volume" "data" {
  name     = "actunode-data"
  size     = var.volume_gb
  location = var.location
  format   = "ext4"
}

resource "hcloud_server" "cloud" {
  name         = "actunode-cloud-1"
  image        = "ubuntu-24.04"
  server_type  = var.server_type
  location     = var.location
  ssh_keys     = [hcloud_ssh_key.admin.id]
  firewall_ids = [hcloud_firewall.edge.id]
  backups      = true
  user_data = templatefile("${path.module}/cloud-init.yaml", {
    volume_id = hcloud_volume.data.id
    domain    = var.domain
    release   = var.release
  })
  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }
}

resource "hcloud_volume_attachment" "data" {
  volume_id = hcloud_volume.data.id
  server_id = hcloud_server.cloud.id
  automount = false # cloud-init mounts it at /srv/actunode
}

output "ipv4" {
  value = hcloud_server.cloud.ipv4_address
}

output "ipv6" {
  value = hcloud_server.cloud.ipv6_address
}

output "dns_records" {
  description = "Create these at your DNS provider"
  value = [
    "app.${var.domain}  A     ${hcloud_server.cloud.ipv4_address}",
    "*.${var.domain}    A     ${hcloud_server.cloud.ipv4_address}",
    "app.${var.domain}  AAAA  ${hcloud_server.cloud.ipv6_address}",
    "*.${var.domain}    AAAA  ${hcloud_server.cloud.ipv6_address}",
  ]
}
