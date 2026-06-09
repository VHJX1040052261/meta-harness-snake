// js/main.js
function init() {
  initBoard();
  nextPiece = createRandomPiece();
  spawnPiece();
  hideGameOver();
  draw();
}

function startGame() {
  if (gameOver) { resetGame(); return; }
  if (isRunning) return;
  isRunning = true;
  isPaused = false;
  gameOver = false;
  hideGameOver();
  lastTime = performance.now();
  dropCounter = 0;
  requestAnimationFrame(gameLoop);
}

function pauseGame() {
  if (!isRunning || gameOver) return;
  isPaused = !isPaused;
  if (!isPaused) {
    lastTime = performance.now();
    dropCounter = 0;
  }
}

function resetGame() {
  isRunning = false;
  isPaused = false;
  gameOver = false;
  score = 0;
  level = 1;
  lines = 0;
  dropInterval = 1000;
  dropCounter = 0;
  initBoard();
  nextPiece = createRandomPiece();
  spawnPiece();
  hideGameOver();
  draw();
  lastTime = performance.now();
  isRunning = true;
  requestAnimationFrame(gameLoop);
}

document.getElementById('start-btn').addEventListener('click', startGame);
document.getElementById('pause-btn').addEventListener('click', pauseGame);
document.getElementById('restart-btn').addEventListener('click', resetGame);
document.getElementById('overlay-restart-btn').addEventListener('click', resetGame);

init();