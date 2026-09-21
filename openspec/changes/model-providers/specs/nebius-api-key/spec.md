## REMOVED Requirements

### Requirement: Save a Nebius API key

**Reason**: Keys are now kept per provider, and Nebius is one provider among several.
**Migration**: See "Save a provider API key" in the `provider-keys` capability. Existing Nebius keys are kept as the `nebius` provider's key.

### Requirement: Key is stored encrypted and never returned

**Reason**: Moved to the provider-neutral capability with the same rules.
**Migration**: See "Key is stored encrypted and never returned" in the `provider-keys` capability.

### Requirement: View key status

**Reason**: Status is now shown per provider.
**Migration**: See "View key status" in the `provider-keys` capability.

### Requirement: Replace a Nebius API key

**Reason**: Moved to the provider-neutral capability.
**Migration**: See "Replace a provider API key" in the `provider-keys` capability.

### Requirement: Delete a Nebius API key

**Reason**: Moved to the provider-neutral capability.
**Migration**: See "Delete a provider API key" in the `provider-keys` capability.

### Requirement: Key used only on the server

**Reason**: Moved to the provider-neutral capability.
**Migration**: See "Key used only on the server" in the `provider-keys` capability.

### Requirement: Clear errors when a key is missing or stops working

**Reason**: The error codes are renamed `provider_key_missing` and `provider_key_rejected`.
**Migration**: See "Clear errors when a key is missing or stops working" in the `provider-keys` capability.
