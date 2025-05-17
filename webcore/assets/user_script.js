let tg = window.Telegram.WebApp;
tg.ready();

const user = tg.initDataUnsafe.user;

document.getElementById("info").innerHTML = `
  <p><strong>ID:</strong> ${user.id}</p>
  <p><strong>First Name:</strong> ${user.first_name}</p>
  <p><strong>Last Name:</strong> ${user.last_name || "None"}</p>
  <p><strong>Username:</strong> @${user.username}</p>
  <p><strong>Language:</strong> ${user.language_code}</p>
  <p><strong>Premium:</strong> ${user.is_premium ? "Yes" : "No"}</p>
`;

fetch("/submit", {
  method: "POST",
  headers: {
    "Content-Type": "application/json"
  },
  body: JSON.stringify(user)
});
