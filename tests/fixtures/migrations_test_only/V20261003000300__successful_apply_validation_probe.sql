-- manager:migration=test-only version=20261003000300 checksum=529763174d46d3203402b037635cdb1d55b1792e80d953517e31e12caead5379
-- TEST ONLY: isolated nonproduction validation of a successful apply.
-- Creates one dedicated empty technical table and exercises result draining.
-- No application data, credentials, or dependency on V20261003000200.
CREATE TABLE manager_successful_apply_validation_probe (
    probe_key VARCHAR(32) NOT NULL PRIMARY KEY,
    note VARCHAR(80) NOT NULL
);
SELECT 1;
