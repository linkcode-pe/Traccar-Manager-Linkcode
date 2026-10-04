-- manager:migration=test-only version=20261003000200 checksum=9af4bd3bc65234eaa817e808833c953ffdb2fa5ceda89f0071c5f3a0b3dcba5a
-- Controlled isolated failure; read-only statements only.
SELECT 1;
SELECT * FROM manager_failure_probe_missing_20261003000200;
