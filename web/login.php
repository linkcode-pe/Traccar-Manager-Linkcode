<?php
declare(strict_types=1);
ini_set('session.use_strict_mode','1');
ini_set('session.use_only_cookies','1');
ini_set('session.gc_maxlifetime','1800');
session_set_cookie_params(['lifetime'=>0,'path'=>'/panel/','secure'=>true,'httponly'=>true,'samesite'=>'Lax']);
session_start();
header('Cache-Control: no-store, private');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: same-origin');
try {$auth=require '/etc/traccar-panel/auth.php';} catch(Throwable $e) {http_response_code(500);exit('No se pudo iniciar sesión.');}
$expectedUser=is_array($auth)?($auth['username']??''):'';
$storedHash=is_array($auth)?($auth['password_hash']??''):'';
if(!is_string($expectedUser)||!is_string($storedHash)){http_response_code(500);exit('No se pudo iniciar sesión.');}
if(($_SESSION['panel_authenticated']??false)===true){$loginTime=$_SESSION['panel_login_time']??0;if(is_int($loginTime)&&(time()-$loginTime)<1800){header('Location: /panel/',true,303);exit;}$_SESSION=[];session_regenerate_id(true);}
if(!isset($_SESSION['panel_login_csrf'])||!is_string($_SESSION['panel_login_csrf']))$_SESSION['panel_login_csrf']=bin2hex(random_bytes(32));
$errorMessage='';
if(($_SERVER['REQUEST_METHOD']??'GET')==='POST'){
 $submittedUser=is_string($_POST['username']??null)?$_POST['username']:'';
 $submittedPassword=is_string($_POST['password']??null)?$_POST['password']:'';
 $submittedCsrf=is_string($_POST['csrf_token']??null)?$_POST['csrf_token']:'';
 $csrfOk=hash_equals($_SESSION['panel_login_csrf'],$submittedCsrf);
 $userOk=hash_equals($expectedUser,$submittedUser);
 $passwordOk=password_verify($submittedPassword,$storedHash);
 if($csrfOk&&$userOk&&$passwordOk){session_regenerate_id(true);$_SESSION=[];$_SESSION['panel_authenticated']=true;$_SESSION['panel_user']='paneladmin';$_SESSION['panel_login_time']=time();header('Location: /panel/',true,303);exit;}
 $errorMessage='Usuario o contraseña incorrectos.';
 $_SESSION['panel_login_csrf']=bin2hex(random_bytes(32));
}
$loginCss=@file_get_contents(__DIR__.'/login.css');
if(!is_string($loginCss))$loginCss='';
$csrfForForm=htmlspecialchars($_SESSION['panel_login_csrf'],ENT_QUOTES|ENT_SUBSTITUTE,'UTF-8');
$errorForHtml=htmlspecialchars($errorMessage,ENT_QUOTES|ENT_SUBSTITUTE,'UTF-8');
?>
<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>TRACCAR PANEL · Acceso</title><style><?= $loginCss ?></style></head>
<body><main class="page"><section class="login-card" aria-labelledby="login-title"><div class="brand-mark" aria-hidden="true">T</div><p class="eyebrow">TRACCAR PANEL</p><h1 id="login-title">Monitoreo y gestión de vehículos</h1><p class="intro">Ingresa tus datos para continuar.</p>
<?php if($errorMessage!==''):?><div class="error-message" role="alert"><?= $errorForHtml ?></div><?php endif;?>
<form method="post" action="/panel/login.php" autocomplete="on"><input type="hidden" name="csrf_token" value="<?= $csrfForForm ?>"><label for="username">Usuario</label><input id="username" name="username" type="text" autocomplete="username" maxlength="128" required autofocus><label for="password">Contraseña</label><input id="password" name="password" type="password" autocomplete="current-password" maxlength="1024" required><button type="submit">ACCEDER</button></form></section>
<footer class="page-footer"><p class="tagline">Panel de monitoreo profesional para servidores Traccar</p><section class="contact-card" aria-label="Contacto"><p class="contact-question">¿Quieres un panel como este para tu servidor Traccar?</p><p class="phone">WhatsApp: 902 236 750</p><a class="whatsapp-button" href="https://wa.me/51902236750" target="_blank" rel="noopener noreferrer">💬 CONTACTAR POR WHATSAPP</a></section></footer></main></body></html>
