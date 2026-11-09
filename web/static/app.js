// The message box and small page behaviors. Everything else that moves
// on the page is done by HTMX.
//
// The message box is replaced with a fresh, empty one after each send, so
// listeners are put on the whole document and check which element the
// event came from. They keep working for every new box.

// A finger, not a mouse: a phone. Its Enter key adds a line, and it has
// the Send button; focusing a box there would pop the keyboard up.
const isTouch = window.matchMedia("(pointer: coarse)").matches;

// Make the box exactly as tall as its text. CSS caps how tall it can get.
function fitToText(box) {
  box.style.height = "auto";
  const borders = box.offsetHeight - box.clientHeight;
  box.style.height = box.scrollHeight + borders + "px";
}

function showSendError(text) {
  const note = document.getElementById("send-error");
  note.textContent = text;
  note.hidden = text === "";
}

document.addEventListener("keydown", function (event) {
  if (event.target.id !== "message" || event.key !== "Enter") return;
  // Shift+Enter, or Enter on a phone: let the box add a new line.
  // isComposing: Enter is confirming an accented or foreign character.
  if (event.shiftKey || isTouch || event.isComposing) return;

  event.preventDefault(); // stop this Enter from adding a line
  const send = document.getElementById("send");
  if (event.target.value.trim() !== "" && !send.disabled) {
    event.target.form.requestSubmit(); // the same as pressing Send
  }
});

document.addEventListener("input", function (event) {
  if (event.target.id === "message") fitToText(event.target);
});

// HTMX announces each finished request with this event.
document.addEventListener("htmx:afterRequest", function (event) {
  if (event.detail.requestConfig.verb !== "post") return; // not the status checks

  const fromMessageBox = event.target.id === "composer";
  if (event.detail.successful) {
    showSendError("");
    if (fromMessageBox && !isTouch) document.getElementById("message").focus();
  } else if (event.detail.xhr?.status === 409) {
    // On a phone the chat list is its own screen, where the note can't be seen.
    const busy = "This chat is still being answered. Try again when the reply is done.";
    if (event.target.closest?.("#chat-list")) window.alert(busy);
    else showSendError(busy);
  } else if (event.target.closest?.("#chat-list")) {
    window.alert("That didn't go through. Check your connection and try again.");
  } else if (fromMessageBox) {
    showSendError("That didn't send, but your message is still in the box. " +
                  "Check your connection and press Send again. If it keeps happening, reload the page.");
  } else {
    showSendError("That didn't go through. Check your connection and try again. " +
                  "If it keeps happening, reload the page.");
  }
});

// Clicking the pencil: have the name selected, ready to type over. "toggle"
// doesn't travel up the page like most events, so this listens with
// capture (the true at the end), which sees it on the way down.
document.addEventListener("toggle", function (event) {
  if (event.target.matches?.(".rename") && event.target.open) {
    event.target.querySelector("input").select();
  }
}, true);

// When a chat opens, start at its latest message and be ready to type.
// A URL ending in #chat-list is the phone's chat list screen: leave it.
document.addEventListener("DOMContentLoaded", function () {
  if (window.location.hash) return;
  const box = document.getElementById("message");
  if (!box) return; // the sign-in and error pages have no message box

  const messages = document.querySelectorAll("#messages .message");
  if (messages.length > 0) messages[messages.length - 1].scrollIntoView();
  if (!isTouch) box.focus({ preventScroll: true });
});
