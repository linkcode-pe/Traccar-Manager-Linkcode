<?php
declare(strict_types=1);
ini_set('session.use_strict_mode','1');
ini_set('session.use_only_cookies','1');
ini_set('session.gc_maxlifetime','1800');
session_set_cookie_params(['lifetime'=>0,'path'=>'/panel/','secure'=>true,'httponly'=>true,'samesite'=>'Lax']);
session_start();
$_SESSION=[];
setcookie(session_name(),'',['expires'=>time()-42000,'path'=>'/panel/','secure'=>true,'httponly'=>true,'samesite'=>'Lax']);
session_destroy();
header('Location: /panel/login.php',true,302);
exit;
