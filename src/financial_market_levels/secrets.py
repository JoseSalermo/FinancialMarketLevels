"""Secret resolution: Vault -> env vars -> mounted files.

Phase 6 will copy the sibling app's pattern verbatim (with VAULT_SECRET_PATH
defaulted to secret/data/financial-market-levels). No secrets are required
at MVP since yfinance is the only data source.
"""
