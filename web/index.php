<?php
declare(strict_types=1);
require_once '/etc/traccar-panel/session_guard.php';
date_default_timezone_set('America/Lima');
ini_set('display_errors', '0');
ini_set('log_errors', '1');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header("Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'");
function h($v): string { return htmlspecialchars((string)($v ?? ''), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function n($v, int $d=0): string { return ($v === null || !is_numeric($v)) ? '—' : number_format((float)$v, $d, '.', ','); }
function gib($v): string { return ($v === null || !is_numeric($v)) ? '—' : number_format((float)$v/1073741824, 2, '.', ',').' GiB'; }
function panelLog(string $where, Throwable $e): void { error_log('[Traccar Panel]['.$where.'] '.get_class($e).': '.$e->getMessage()); }
function one(PDO $pdo, string $sql): array { $s=$pdo->prepare($sql); $s->execute(); $r=$s->fetch(); return is_array($r) ? $r : []; }
function many(PDO $pdo, string $sql): array { $s=$pdo->prepare($sql); $s->execute(); return $s->fetchAll(); }
$pdo=null; $dbOk=false; $queryErrors=0;
$devices=['total_devices'=>null,'enabled_devices'=>null,'disabled_devices'=>null];
$table=['table_rows'=>null,'data_length'=>null,'index_length'=>null];
$older=null; $positions=[];
try {
    $cfg=require '/etc/traccar-panel-db.php';
    if (!is_array($cfg) || ($cfg['username'] ?? null) !== 'panel_readonly') { throw new RuntimeException('Invalid panel DB configuration'); }
    $dsn='mysql:host='.$cfg['host'].';dbname='.$cfg['database'].';charset=utf8mb4';
    $pdo=new PDO($dsn,$cfg['username'],$cfg['password'],$cfg['options'] ?? []);
    $dbOk=true;
} catch (Throwable $e) { panelLog('connection',$e); }
if ($dbOk && $pdo instanceof PDO) {
    try {
        $devices=one($pdo,"SELECT COUNT(*) AS total_devices,
            COALESCE(SUM(CASE WHEN disabled = b'0' OR disabled IS NULL THEN 1 ELSE 0 END),0) AS enabled_devices,
            COALESCE(SUM(CASE WHEN disabled = b'1' THEN 1 ELSE 0 END),0) AS disabled_devices
            FROM plataforma.tc_devices");
    } catch (Throwable $e) { $queryErrors++; panelLog('devices',$e); }
    try {
        $table=one($pdo,"SELECT table_rows,data_length,index_length FROM information_schema.tables
            WHERE table_schema='plataforma' AND table_name='tc_positions' LIMIT 1");
    } catch (Throwable $e) { $queryErrors++; panelLog('positions-size',$e); }
    try {
        $olderRow=one($pdo,"SELECT COUNT(*) AS current_old_positions
            FROM plataforma.tc_devices AS d
            STRAIGHT_JOIN plataforma.tc_positions AS p ON p.id = d.positionid
            WHERE d.positionid IS NOT NULL
              AND p.fixtime < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 90 DAY)");
        $older=$olderRow['current_old_positions'] ?? $olderRow['CURRENT_OLD_POSITIONS'] ?? null;
    } catch (Throwable $e) { $queryErrors++; }
    try {
        $positions=many($pdo,"SELECT d.name,d.uniqueid,d.status,d.lastupdate,
            p.fixtime,p.latitude,p.longitude,p.speed,p.course,p.address
            FROM plataforma.tc_devices AS d
            INNER JOIN plataforma.tc_positions AS p ON d.positionid = p.id
            ORDER BY d.name ASC,d.id ASC
            LIMIT 200");
    } catch (Throwable $e) { $queryErrors++; panelLog('current-positions',$e); }
}
$qState=!$dbOk ? 'error' : ($queryErrors===0 ? 'ok' : 'partial');
$tableRows=$table['TABLE_ROWS'] ?? $table['table_rows'] ?? null;
$dataLen=$table['DATA_LENGTH'] ?? $table['data_length'] ?? null; $indexLen=$table['INDEX_LENGTH'] ?? $table['index_length'] ?? null;
$totalLen=null;
if (is_numeric($dataLen) && is_numeric($indexLen)) { $totalLen=(float)$dataLen+(float)$indexLen; }
$updated=date('d/m/Y H:i:s').' · America/Lima';
$retentionStatusPath = '/var/lib/traccar-retencion-90d/status';
$retentionAllowedFields = ['last_start', 'last_end', 'last_result', 'last_remaining', 'last_message', 'last_update'];
$retentionData = [];
$retentionStatusText = '⚪ Sin datos todavía';
$retentionServiceClass = 'pending';
$retentionStart = $retentionEnd = $retentionUpdated = $retentionCount = '—';
$retentionStateMap = [
    'running' => ['🟢 Ejecutando', 'ok'],
    'time_limit' => ['🟡 Ciclo finalizado por límite de tiempo', 'pending'],
    'completed' => ['🟢 Recorrido completado', 'ok'],
    'error' => ['🔴 Error', 'error-state'],
    'locked' => ['🔵 Otra ejecución activa', 'pending'],
];
$retentionFormatError = false;
if (file_exists($retentionStatusPath)) {
    if (!is_file($retentionStatusPath) || !is_readable($retentionStatusPath)) {
        $retentionStatusText = '🔴 Estado no disponible';
        $retentionServiceClass = 'error-state';
    } else {
        $retentionLines = @file($retentionStatusPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        if ($retentionLines === false) {
            $retentionStatusText = '🔴 Estado no disponible';
            $retentionServiceClass = 'error-state';
        } elseif ($retentionLines !== []) {
            foreach ($retentionLines as $retentionLine) {
                $retentionSeparator = strpos($retentionLine, '=');
                if ($retentionSeparator === false) {
                    continue;
                }
                $retentionKey = substr($retentionLine, 0, $retentionSeparator);
                if (in_array($retentionKey, $retentionAllowedFields, true)) {
                    $retentionData[$retentionKey] = trim(substr($retentionLine, $retentionSeparator + 1));
                }
            }
            if ($retentionData === []) {
                $retentionFormatError = true;
            } else {
                $retentionResult = $retentionData['last_result'] ?? '';
                if (!array_key_exists($retentionResult, $retentionStateMap)) {
                    $retentionFormatError = true;
                } else {
                    [$retentionStatusText, $retentionServiceClass] = $retentionStateMap[$retentionResult];
                }
                $retentionDate = static function (?string $value): ?string {
                    if ($value === null || $value === '') {
                        return '—';
                    }
                    if (!preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$/D', $value)) {
                        return null;
                    }
                    try {
                        return (new DateTimeImmutable($value))->format('d/m/Y H:i:s P');
                    } catch (Throwable $e) {
                        return null;
                    }
                };
                foreach (['last_start' => 'retentionStart', 'last_end' => 'retentionEnd', 'last_update' => 'retentionUpdated'] as $retentionField => $retentionTarget) {
                    $retentionFormatted = $retentionDate($retentionData[$retentionField] ?? null);
                    if ($retentionFormatted === null) {
                        $retentionFormatError = true;
                    } else {
                        $$retentionTarget = $retentionFormatted;
                    }
                }
                $retentionRemaining = $retentionData['last_remaining'] ?? null;
                if ($retentionRemaining !== null && $retentionRemaining !== '') {
                    if (!preg_match('/^\d+$/D', $retentionRemaining)) {
                        $retentionFormatError = true;
                    } else {
                        $retentionCount = $retentionRemaining;
                    }
                }
            }
            if ($retentionFormatError) {
                $retentionStatusText = 'Estado de retención no disponible';
                $retentionServiceClass = 'error-state';
                $retentionStart = $retentionEnd = $retentionUpdated = $retentionCount = '—';
            }
        }
    }
}
$log30StatusPath = '/var/lib/traccar-log-retencion-30d/status';
$log30AllowedFields = ['last_start', 'last_end', 'last_result', 'last_deleted', 'last_bytes', 'last_cutoff', 'last_message', 'last_update'];
$log30Data = [];
$log30StatusText = 'No disponible';
$log30ResultText = '—';
$log30StatusClass = 'error-state';
$log30Message = '—';
$log30StatusSize = @filesize($log30StatusPath);
if (is_file($log30StatusPath) && is_readable($log30StatusPath) && $log30StatusSize !== false && $log30StatusSize <= 16384) {
    $log30Lines = @file($log30StatusPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if (is_array($log30Lines)) {
        foreach ($log30Lines as $log30Line) {
            $log30Separator = strpos($log30Line, '=');
            if ($log30Separator === false) {
                continue;
            }
            $log30Key = substr($log30Line, 0, $log30Separator);
            if (in_array($log30Key, $log30AllowedFields, true)) {
                $log30Value = trim(substr($log30Line, $log30Separator + 1));
                if (strlen($log30Value) > 2048) {
                    $log30Value = substr($log30Value, 0, 2048);
                }
                $log30Data[$log30Key] = $log30Value;
            }
        }
        $log30StatusClass = 'pending';
        $log30StatusText = '—';
        $log30Result = $log30Data['last_result'] ?? '';
        $log30ResultMap = [
            'completed' => 'Completado',
            'running' => 'Ejecutándose',
            'error' => 'Error',
            'locked' => 'Bloqueado',
        ];
        if (array_key_exists($log30Result, $log30ResultMap)) {
            $log30ResultText = $log30ResultMap[$log30Result];
            $log30StatusText = $log30ResultText;
            $log30StatusClass = $log30Result === 'completed' ? 'ok' : ($log30Result === 'error' ? 'error-state' : 'pending');
        }
        $log30MessageValue = $log30Data['last_message'] ?? '';
        $log30Message = $log30MessageValue !== '' ? $log30MessageValue : '—';
    }
}
$log30DeletedFiles = '—';
$log30DeletedRaw = $log30Data['last_deleted'] ?? null;
if (is_string($log30DeletedRaw) && preg_match('/^\d+$/D', $log30DeletedRaw)) {
    $log30DeletedFiles = number_format((float)$log30DeletedRaw, 0, '.', ',');
}
$log30BytesRaw = $log30Data['last_bytes'] ?? null;
$log30BytesReadable = '—';
if (is_string($log30BytesRaw) && preg_match('/^\d+$/D', $log30BytesRaw)) {
    $log30BytesValue = (float)$log30BytesRaw;
    if ($log30BytesValue >= 1073741824) {
        $log30BytesReadable = number_format($log30BytesValue / 1073741824, 2, '.', ',') . ' GiB';
    } elseif ($log30BytesValue >= 1048576) {
        $log30BytesReadable = number_format($log30BytesValue / 1048576, 2, '.', ',') . ' MiB';
    } else {
        $log30BytesReadable = number_format($log30BytesValue, 0, '.', ',') . ' bytes';
    }
}
$log30HistoricalCount = '—';
$log30CandidatesCount = '—';
$log30LogDir = '/opt/traccar/logs';
$log30CutoffTimestamp = strtotime('30 days ago');
if ($log30CutoffTimestamp !== false && is_dir($log30LogDir) && is_readable($log30LogDir)) {
    $log30Matches = @glob($log30LogDir . '/tracker-server.log.????????');
    if (is_array($log30Matches)) {
        $log30History = 0;
        $log30Candidates = 0;
        $log30CandidatesBytes = 0;
        $log30ScanOk = true;
        foreach ($log30Matches as $log30Path) {
            $log30Base = basename($log30Path);
            if ($log30Base === 'tracker-server.log' || !preg_match('/^tracker-server\.log\.[0-9]{8}$/D', $log30Base) || !is_file($log30Path) || is_link($log30Path)) {
                continue;
            }
            $log30History++;
            $log30Mtime = @filemtime($log30Path);
            if ($log30Mtime === false) {
                $log30ScanOk = false;
                break;
            }
            if ($log30Mtime <= $log30CutoffTimestamp) {
                $log30FileSize = @filesize($log30Path);
                if ($log30FileSize === false) {
                    $log30ScanOk = false;
                    break;
                }
                $log30Candidates++;
                $log30CandidatesBytes += $log30FileSize;
            }
        }
        $log30HistoricalCount = (string)$log30History;
        if ($log30ScanOk) {
            $log30CandidatesCount = (string)$log30Candidates;
        }
    }
}
$log30DiskFreeDisplay = '—';
$log30DiskUsedDisplay = '—';
$log30DiskPercentDisplay = '—';
$log30DiskFreePercentDisplay = '—';
$log30DiskSummaryAvailable = false;
$log30DiskFree = @disk_free_space('/');
$log30DiskTotal = @disk_total_space('/');
if (is_numeric($log30DiskFree) && is_numeric($log30DiskTotal) && (float)$log30DiskTotal > 0 && (float)$log30DiskFree >= 0 && (float)$log30DiskFree <= (float)$log30DiskTotal) {
    $log30DiskUsed = (float)$log30DiskTotal - (float)$log30DiskFree;
    $log30DiskFreeDisplay = number_format((float)$log30DiskFree / 1073741824, 2, '.', ',') . ' GiB';
    $log30DiskUsedDisplay = number_format($log30DiskUsed / 1073741824, 2, '.', ',') . ' GiB';
    $log30DiskPercentDisplay = number_format(($log30DiskUsed / (float)$log30DiskTotal) * 100, 1, '.', ',') . '%';
    $log30DiskFreePercentDisplay = number_format(((float)$log30DiskFree / (float)$log30DiskTotal) * 100, 1, '.', ',') . '%';
    $log30DiskSummaryAvailable = true;
}

$traccarStatusPath = '/var/lib/traccar-panel-status/status';
$traccarStatusAllowed = [
    'active_state' => true,
    'sub_state' => true,
    'active_enter_timestamp' => true,
    'exec_main_start_timestamp' => true,
    'n_restarts' => true,
    'last_update' => true,
];
$traccarStatusValues = [];
$traccarStatusFresh = false;
$traccarStatusClass = 'pending';
$traccarStatusLabel = 'Sin datos recientes';
$traccarSubstateLabel = '';
if (is_file($traccarStatusPath) && is_readable($traccarStatusPath)) {
    $traccarStatusRaw = @file_get_contents($traccarStatusPath, false, null, 0, 4097);
    if ($traccarStatusRaw !== false && strlen($traccarStatusRaw) <= 4096 && strpos($traccarStatusRaw, "\0") === false) {
        $traccarStatusParsed = [];
        $traccarStatusParseOk = true;
        foreach (explode("\n", $traccarStatusRaw) as $traccarStatusLine) {
            if ($traccarStatusLine === '') {
                continue;
            }
            if (strpos($traccarStatusLine, "\r") !== false) {
                $traccarStatusParseOk = false;
                break;
            }
            $traccarStatusSeparator = strpos($traccarStatusLine, '=');
            if ($traccarStatusSeparator === false) {
                $traccarStatusParseOk = false;
                break;
            }
            $traccarStatusKey = substr($traccarStatusLine, 0, $traccarStatusSeparator);
            $traccarStatusValue = substr($traccarStatusLine, $traccarStatusSeparator + 1);
            if (array_key_exists($traccarStatusKey, $traccarStatusAllowed)) {
                if (array_key_exists($traccarStatusKey, $traccarStatusParsed)) {
                    $traccarStatusParseOk = false;
                    break;
                }
                $traccarStatusParsed[$traccarStatusKey] = $traccarStatusValue;
            }
        }
        if ($traccarStatusParseOk && count($traccarStatusParsed) === count($traccarStatusAllowed)) {
            $traccarStatePattern = '/\A[a-zA-Z0-9_.+-]{1,64}\z/D';
            $traccarTimestampPattern = '/\A[A-Za-z0-9 .:+\/-]{1,128}\z/D';
            $traccarStateValid = preg_match($traccarStatePattern, $traccarStatusParsed['active_state']) === 1;
            $traccarSubstateValid = preg_match($traccarStatePattern, $traccarStatusParsed['sub_state']) === 1;
            $traccarStartValid = preg_match($traccarTimestampPattern, $traccarStatusParsed['active_enter_timestamp']) === 1;
            $traccarExecStartValid = preg_match($traccarTimestampPattern, $traccarStatusParsed['exec_main_start_timestamp']) === 1;
            $traccarRestarts = filter_var($traccarStatusParsed['n_restarts'], FILTER_VALIDATE_INT, ['options' => ['min_range' => 0]]);
            $traccarUpdateMatch = [];
            $traccarUpdateValid = preg_match('/\A(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) -05\z/D', $traccarStatusParsed['last_update'], $traccarUpdateMatch) === 1;
            if ($traccarStateValid && $traccarSubstateValid && $traccarStartValid && $traccarExecStartValid && $traccarRestarts !== false && $traccarUpdateValid) {
                $traccarUpdateDate = DateTimeImmutable::createFromFormat('!Y-m-d H:i:s', $traccarUpdateMatch[1], new DateTimeZone('America/Lima'));
                $traccarDateErrors = DateTimeImmutable::getLastErrors();
                $traccarDateValid = $traccarUpdateDate !== false
                    && ($traccarDateErrors === false || ($traccarDateErrors['warning_count'] === 0 && $traccarDateErrors['error_count'] === 0))
                    && $traccarUpdateDate->format('Y-m-d H:i:s') === $traccarUpdateMatch[1];
                if ($traccarDateValid) {
                    $traccarAge = time() - $traccarUpdateDate->getTimestamp();
                    $traccarStatusFresh = $traccarAge >= 0 && $traccarAge <= 600;
                }
            }
            if ($traccarStatusFresh) {
                $traccarStatusValues = $traccarStatusParsed;
                if ($traccarStatusValues['active_state'] === 'active' && $traccarStatusValues['sub_state'] === 'running') {
                    $traccarStatusClass = 'ok';
                    $traccarStatusLabel = 'Activo';
                    $traccarSubstateLabel = $traccarStatusValues['sub_state'];
                } else {
                    $traccarStatusLabel = 'Estado: ' . $traccarStatusValues['active_state'];
                    $traccarSubstateLabel = 'Subestado: ' . $traccarStatusValues['sub_state'];
                }
            }
        }
    }
}
?>
<!doctype html>
<html lang="es" data-db-state="<?= $dbOk?'connected':'error' ?>" data-query-state="<?= h($qState) ?>">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<title>TRACCAR SERVER · Panel</title>
<link rel="stylesheet" href="/panel/assets/style.css"><script src="/panel/assets/app.js" defer></script>
</head>
<body><div class="shell">
<header class="topbar"><div class="brand"><div class="mark" aria-hidden="true">T</div><div><p class="eyebrow">MONITOREO DEL SERVIDOR</p><h1>TRACCAR SERVER</h1><p class="muted">Estado general y posiciones actuales</p></div></div>
<div class="actions"><div class="updated"><span>Última actualización</span><time><?= h($updated) ?></time></div><button type="button" class="refresh" data-action="refresh"><span aria-hidden="true">↻</span> Actualizar</button></div></header>
<main class="dashboard" data-db-state="<?= $dbOk?'connected':'error' ?>" data-query-state="<?= h($qState) ?>" data-position-rows="<?= count($positions) ?>">
<?php if (!$dbOk): ?><div class="notice error" role="alert">Error de conexión con la base de datos.</div><?php elseif ($queryErrors>0): ?><div class="notice warn" role="status">No se pudieron cargar algunos datos. Intenta actualizar.</div><?php endif; ?>
<section class="service-grid" aria-label="Estado del servidor">
<article class="service-card <?= $dbOk?'ok':'error-state' ?>"><span class="icon">DB</span><span class="service-text"><small>MySQL</small><strong><?= $dbOk?'Conectado':'Error' ?></strong></span><i class="dot"></i></article>
<article class="service-card <?= h($traccarStatusClass) ?>"><span class="icon">TR</span><span class="service-text"><small>Traccar</small><strong><?= h($traccarStatusLabel) ?></strong><?php if ($traccarStatusFresh): ?><small><?= h($traccarSubstateLabel) ?></small><small>Última actualización: <?= h($traccarStatusValues['last_update']) ?></small><small>Inicio: <?= h($traccarStatusValues['active_enter_timestamp']) ?></small><small>Reinicios: <?= h($traccarStatusValues['n_restarts']) ?></small><?php endif; ?></span><i class="dot"></i></article>
<article class="service-card <?= h($retentionServiceClass) ?>"><span class="icon" aria-hidden="true">90</span><span class="service-text"><small>Retención 90 días</small><strong><?= h($retentionStatusText) ?></strong></span><i class="dot"></i></article>
<article class="service-card <?= $log30DiskSummaryAvailable ? 'ok' : 'pending' ?>"><span class="icon">FS</span><span class="service-text"><small>Disco</small><strong><?= $log30DiskSummaryAvailable ? h('Libre: ' . $log30DiskFreeDisplay . ' · Disponibilidad: ' . $log30DiskFreePercentDisplay) : 'No disponible' ?></strong></span><i class="dot"></i></article>
</section>
<section aria-labelledby="retention-title">
<div class="section-head"><div><p class="eyebrow">PROCESO AUTOMÁTICO</p><h2 id="retention-title">🧹 RETENCIÓN 90 DÍAS</h2></div><span class="section-note">Estado local</span></div>
<div class="stats three">
<article class="stat blue"><span>Estado del último ciclo</span><strong class="compact"><?= h($retentionStatusText) ?></strong><small>Según el último estado registrado</small></article>
<article class="stat violet"><span>Inicio</span><strong class="compact"><?= h($retentionStart) ?></strong><small>Último ciclo</small></article>
<article class="stat violet"><span>Fin</span><strong class="compact"><?= h($retentionEnd) ?></strong><small>Último ciclo</small></article>
</div>
<div class="stats three" style="margin-top:11px">
<article class="stat cyan"><span>Última actualización</span><strong class="compact"><?= h($retentionUpdated) ?></strong><small>Estado de telemetría</small></article>
<article class="stat amber"><span>Último conteo registrado</span><strong><?= h($retentionCount) ?></strong><small>Del último dispositivo procesado; no es un total global</small></article>
<article class="stat blue"><span>Próxima ejecución</span><strong class="compact">Disponible en el próximo estado</strong><small>No se calcula una hora</small></article>
</div>
</section>
<section aria-labelledby="retention-30d-title">
<div class="section-head"><div><p class="eyebrow">PROCESO AUTOMÁTICO</p><h2 id="retention-30d-title">Retención de logs — 30 días</h2></div><span class="section-note">Estado local</span></div>
<div class="stats three">
<article class="stat blue"><span>Estado</span><strong class="compact <?= h($log30StatusClass) ?>"><?= h($log30StatusText) ?></strong><small><?= h($log30Message) ?></small></article>
<article class="stat violet"><span>Última ejecución</span><strong class="compact"><?= h($log30Data['last_start'] ?? '—') ?></strong><small>Inicio del último ciclo</small></article>
<article class="stat violet"><span>Fin del último ciclo</span><strong class="compact"><?= h($log30Data['last_end'] ?? '—') ?></strong><small>Según la telemetría</small></article>
</div>
<div class="stats three" style="margin-top:11px">
<article class="stat cyan"><span>Resultado</span><strong class="compact"><?= h($log30ResultText) ?></strong><small>Estado registrado</small></article>
<article class="stat amber"><span>Logs eliminados</span><strong><?= h($log30DeletedFiles) ?></strong><small>Archivos en el último ciclo</small></article>
<article class="stat blue"><span>Bytes eliminados</span><strong class="compact"><?= h($log30BytesReadable) ?></strong><small><?= h($log30BytesRaw ?? '—') ?> bytes originales</small></article>
</div>
<div class="stats three" style="margin-top:11px">
<article class="stat violet"><span>Cutoff utilizado</span><strong class="compact"><?= h($log30Data['last_cutoff'] ?? '—') ?></strong><small>Del último ciclo</small></article>
<article class="stat cyan"><span>Última actualización</span><strong class="compact"><?= h($log30Data['last_update'] ?? '—') ?></strong><small>Estado de telemetría</small></article>
<article class="stat blue"><span>Históricos actuales</span><strong><?= h($log30HistoricalCount) ?></strong><small>Logs con nombre válido</small></article>
</div>
<div class="stats three" style="margin-top:11px">
<article class="stat amber"><span>Candidatos &gt;30 días</span><strong><?= h($log30CandidatesCount) ?></strong><small>Solo lectura; según fecha de modificación</small></article>
<article class="stat cyan"><span>Espacio libre</span><strong class="compact"><?= h($log30DiskFreeDisplay) ?></strong><small>En / · <?= h($log30DiskUsedDisplay) ?> usados</small></article>
<article class="stat violet"><span>Uso del disco raíz</span><strong><?= h($log30DiskPercentDisplay) ?></strong><small>Usado / total</small></article>
</div>
</section>
<section><div class="section-head"><div><p class="eyebrow">OPERACIÓN</p><h2>Dispositivos</h2></div><span class="section-note">tc_devices</span></div>
<div class="stats three">
<article class="stat cyan"><span>Total</span><strong><?= h(n($devices['total_devices']??null)) ?></strong><small>dispositivos registrados</small></article>
<article class="stat green"><span>Habilitados</span><strong><?= h(n($devices['enabled_devices']??null)) ?></strong><small>disponibles en la cuenta</small></article>
<article class="stat amber"><span>Deshabilitados</span><strong><?= h(n($devices['disabled_devices']??null)) ?></strong><small>fuera de servicio</small></article>
</div></section>
<section><div class="section-head"><div><p class="eyebrow">BASE DE DATOS</p><h2>Posiciones</h2></div><span class="section-note">tc_positions · filas aproximadas</span></div>
<div class="stats three">
<article class="stat violet"><span>Total aproximado</span><strong><?= h(n($tableRows)) ?></strong><small><?= is_numeric($tableRows) ? 'Estimación InnoDB' : 'No disponible' ?></small></article>
<article class="stat amber"><span>Posiciones actuales &gt;90 días</span><strong><?= h(n($older)) ?></strong><small><?= is_numeric($older) ? 'Solo las posiciones referenciadas por dispositivos' : 'No disponible · solo posiciones referenciadas' ?></small></article>
<article class="stat blue"><span>Tamaño total</span><strong class="compact"><?= h(gib($totalLen)) ?></strong><small><?= $totalLen !== null ? 'Datos + índices' : 'No disponible' ?></small></article>
</div><div class="size-row"><div><span>data_length</span><strong><?= h(gib($dataLen)) ?></strong><?php if (!is_numeric($dataLen)): ?><small>No disponible</small><?php endif; ?></div><div><span>index_length</span><strong><?= h(gib($indexLen)) ?></strong><?php if (!is_numeric($indexLen)): ?><small>No disponible</small><?php endif; ?></div></div></section>
<section class="table-section"><div class="section-head"><div><p class="eyebrow">SEGUIMIENTO</p><h2>Posiciones actuales</h2><p class="muted small">Enlace por tc_devices.positionid · máximo 200 dispositivos</p></div></div>
<div class="table-wrap"><table><thead><tr><th>Nombre</th><th>Unique ID</th><th>Status</th><th>Last update</th><th>Fixtime</th><th>Latitude</th><th>Longitude</th><th>Speed</th><th>Course</th><th>Address</th></tr></thead><tbody>
<?php if ($positions===[]): ?><tr><td colspan="10" class="empty">No hay posiciones actuales para mostrar.</td></tr><?php else: foreach ($positions as $p): ?>
<tr><td class="device"><?= h($p['name']??'—') ?></td><td><?= h($p['uniqueid']??'—') ?></td><td><span class="pill"><?= h($p['status']??'—') ?></span></td><td><?= h($p['lastupdate']??'—') ?></td><td><?= h($p['fixtime']??'—') ?></td><td><?= h(n($p['latitude']??null,6)) ?></td><td><?= h(n($p['longitude']??null,6)) ?></td><td><?= h(n($p['speed']??null,2)) ?></td><td><?= h(n($p['course']??null,1)) ?></td><td class="address" title="<?= h($p['address']??'') ?>"><?= h($p['address']??'—') ?></td></tr>
<?php endforeach; endif; ?>
</tbody></table></div><p class="footnote">Las posiciones se enlazan mediante el identificador actual; no se busca MAX(fixtime).</p></section>
<footer class="footer"><span>Panel de solo lectura</span><span>Sin comandos del sistema · Sin acciones administrativas</span></footer>
</main></div></body></html>
