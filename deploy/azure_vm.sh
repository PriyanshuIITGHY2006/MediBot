#!/usr/bin/env bash
# Create the MediBot VM on Azure (run once). Needs: az login. Prints the public DNS name at the end.
#   bash deploy/azure_vm.sh [size] [region]      default: Standard_B2als_v2 (2 vCPU, 4 GB), southindia
set -euo pipefail
AZ=${AZ:-az}
SIZE=${1:-Standard_B2als_v2}
REGION=${2:-southindia}
RG=medibot-rg
VM=medibot-vm
LABEL=${DNS_LABEL:-medibot-$(whoami | tr -cd 'a-z0-9' | head -c 10)}
cd "$(dirname "$0")"

$AZ group create -n $RG -l "$REGION" -o none
$AZ vm create -g $RG -n $VM --image Ubuntu2404 --size "$SIZE" \
  --admin-username azureuser --generate-ssh-keys \
  --public-ip-sku Standard --public-ip-address-dns-name "$LABEL" \
  --os-disk-size-gb 64 --storage-sku StandardSSD_LRS \
  --custom-data cloud-init.yml -o none
$AZ vm open-port -g $RG -n $VM --port 80,443 --priority 900 -o none
# stop billing surprises: shut down nightly at 02:00 IST is OFF by default; enable with AUTO_SHUTDOWN=1
if [ "${AUTO_SHUTDOWN:-0}" = 1 ]; then $AZ vm auto-shutdown -g $RG -n $VM --time 2030 -o none; fi
FQDN=$($AZ vm show -d -g $RG -n $VM --query fqdns -o tsv)
echo "VM ready: $FQDN   (ssh azureuser@$FQDN)"
echo "Next: put DOMAIN=$FQDN in deploy/.env, then: bash deploy/push.sh $FQDN"
