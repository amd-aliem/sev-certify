#!/usr/bin/bash
set -euo pipefail

SEV_VERSIONS=("3.0-0")
SEV_CERT_FILE=""
SET_MILESTONE="${SET_MILESTONE:-false}"

# Determine OS name and version
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME="${ID}"            
    OS_VERSION="${VERSION_ID}" 
    OS_LABEL="${OS_NAME}-${OS_VERSION}"
else
    OS_NAME="$(uname -s)"
    OS_VERSION=""
    OS_LABEL="${OS_NAME}"
fi

# Loop over to generate beacon report for all SEV certificates
for sev_version in "${SEV_VERSIONS[@]}"; do
  # Build title
  if [ -n "$OS_VERSION" ]; then
    SEV_TITLE="${OS_NAME} ${OS_VERSION} SEV version ${sev_version}"
  else
    SEV_TITLE="${OS_NAME} SEV version ${sev_version}"
  fi

  # Obtain SEV Version Content
  SEV_CERT_FILE="${HOME:-/root}/sev_certificate_v${sev_version}.txt"

  # Call beacon
  if [ -e "${SEV_CERT_FILE}" ] && [ -z "$(grep "❌" "${SEV_CERT_FILE}")" ] && [ "${SET_MILESTONE}" == "true" ]; then
    # Add milestone if no errors encountered. MILESTONE is set in mkosi.conf dynamically during build if this is a release build
    beacon report --title "$SEV_TITLE" --body "$SEV_CERT_FILE" --label "certificate" --label "os-${OS_LABEL}" --milestone "v${sev_version}"
  else
    beacon report --title "$SEV_TITLE" --body "$SEV_CERT_FILE" --label "certificate" --label "os-${OS_LABEL}"
  fi

  echo "Published SEV certificate via beacon with title: $SEV_TITLE"
done
