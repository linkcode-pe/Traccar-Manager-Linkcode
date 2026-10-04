-- manager:migration=test-only version=20261003000100 checksum=5a63f6e07bdc25965ed9210ae24a6ad3cc3e609a573009c9268ea4c2c356e287
-- TEST ONLY: harmless schema probe for isolated Manager persistence validation.
-- Creates no rows and contains no credentials or application data.
CREATE TABLE manager_persistence_validation_probe (
    probe_key VARCHAR(32) NOT NULL PRIMARY KEY,
    note VARCHAR(80) NOT NULL
);
