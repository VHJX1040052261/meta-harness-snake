// js/state.js
let board = [];
let currentPiece = null;
let nextPiece = null;
let score = 0;
let level = 1;
let lines = 0;
let gameOver = false;
let isPaused = false;
let isRunning = false;

function initBoard() {
  board = [];
  for (let y = 0; y < ROWS; y++) {
    board[y] = new Array(COLS).fill(0);
  }
}