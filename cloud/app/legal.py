"""Terms and privacy for ActuNode Cloud (the invite-only beta), approved by the founder on 20 Nov 2026.

Facts here must stay true to the code: GitHub sign-in reads the account id, login and primary verified email
(oauth.py); two cookies (main.py); server logs rotated by size (deploy/compose.yml); daily backups, kept 14 days
locally and off-site (deploy/backup.sh); hosting in the EU (infra/main.tf). Change this text when those change.
"""

UPDATED = "20 November 2026"
CONTACT = "hello@actunode.com"

TERMS = f"""
<h1>Terms</h1>
<p class="muted">ActuNode Cloud, invite-only beta. Last updated: {UPDATED}.</p>
<p>These terms cover ActuNode Cloud, the hosted service at app.actunode.com, run by Sudip Paudel, an individual
("we"). The ActuNode software itself is open source under the Apache License 2.0; these terms do not change that
license. Contact: <a href="mailto:{CONTACT}">{CONTACT}</a>.</p>

<h2>1. The beta</h2>
<p>ActuNode Cloud is an invite-only, free beta. It gives you hosted labs for testing VDA 5050 integrations.
Features may change, and the service may be paused or have outages. If we end the beta, we will give at least 30
days' notice so you can download your recordings.</p>

<h2>2. Your account</h2>
<p>You sign in with GitHub and must keep that account secure. You are responsible for what happens in the workspaces
you own, including what the people you invite do there. You may delete your account at any time on the Account
page.</p>

<h2>3. Using the service</h2>
<p>ActuNode Cloud is a <strong>test environment</strong>. Do not use it to control robots in production, or anywhere a
failure could hurt people or damage property.</p>
<p>You must not:</p>
<ul>
<li>attack, overload or probe the service or other users' workspaces, or try to get around its limits;</li>
<li>use it to store or send unlawful content, or data you have no right to share;</li>
<li>share your workspace logins with people you have not invited.</li>
</ul>
<p>We may suspend an account or workspace that breaks these rules or puts the service or other users at risk. Where
we can, we will tell you first.</p>

<h2>4. Your data</h2>
<p>Your recordings and other workspace data are yours. We use them only to run the service, as described on the
<a href="/privacy">Privacy</a> page. We do not sell them or use them to train AI models.</p>

<h2>5. No warranty</h2>
<p>The beta is provided "as is", without any warranty, to the extent the law allows. Keep your own copies of
recordings you need.</p>

<h2>6. Liability</h2>
<p>To the extent the law allows, we are not liable for indirect or consequential losses, or for lost data, profits
or business, and our total liability is limited to USD 100. Nothing in these terms limits liability that cannot be
limited by law, or rights you have as a consumer that cannot be waived.</p>

<h2>7. Changes and governing law</h2>
<p>We may update these terms; we will tell beta users before significant changes take effect. These terms are
governed by the laws of the State of Texas, USA, except where the law of your country gives you protections that
cannot be waived.</p>
"""

PRIVACY = f"""
<h1>Privacy</h1>
<p class="muted">ActuNode Cloud, invite-only beta. Last updated: {UPDATED}.</p>
<p>ActuNode Cloud is run by Sudip Paudel, an individual (not a company). If you have a question about your data, or
want to use any of the rights below, write to <a href="mailto:{CONTACT}">{CONTACT}</a>.</p>

<h2>What we collect</h2>
<p><strong>When you sign in with GitHub</strong> we receive your GitHub account number, your GitHub username, and your
primary verified email address. We do not receive your name, your picture, your repositories or your GitHub
password.</p>
<p><strong>Your account:</strong> that username and email, the date you joined, the workspaces you create or join and
your role in them, and invitations you send (the invited person's GitHub username and the role you offered).</p>
<p><strong>Your workspaces:</strong> whatever you and your robots or fleet manager send to your lab: VDA 5050
messages, recordings, the lab's audit trail, and the robot and fleet manager logins you create. Recordings are
limited to 2 GB per workspace.</p>
<p><strong>Server logs:</strong> like most websites, our web server logs each request: your IP address, the time,
the address requested and your browser's name. We use them to keep the service secure and to fix problems. They are
rotated automatically and kept only up to a small fixed size.</p>
<p><strong>Cookies:</strong> two, both needed to sign you in: a session cookie (7 days, or until you sign out) and a
short-lived cookie used only during sign-in (10 minutes). No advertising cookies, no analytics, no tracking.</p>

<h2>Why we use it</h2>
<p>To sign you in, run the workspaces you create, let the people you invite join them, and keep the service secure.
Under the EU GDPR, the legal basis is providing the service you asked for, and our legitimate interest in keeping it
secure (server logs). We do not sell your data, show ads, or use your data to train AI models.</p>

<h2>Where it is kept and who else handles it</h2>
<ul>
<li><strong>Hetzner Online GmbH</strong> hosts the service in the EU (Germany by default; Finland is possible). Daily
backups are encrypted and stored with Hetzner.</li>
<li><strong>GitHub</strong> handles the sign-in step when you choose "Sign in with GitHub".</li>
<li><strong>Let's Encrypt</strong> issues the site's HTTPS certificates. It receives no data about you.</li>
<li><strong>Health alerts</strong> sent to the operator's phone may mention workspace addresses, never their
contents.</li>
</ul>

<h2>How long we keep it</h2>
<ul>
<li>Account data: until you delete your account.</li>
<li>Workspace data: until the workspace is deleted, by you or by the deletion of your account.</li>
<li>Backups: kept 14 days, so deleted data is gone from backups within 14 days.</li>
<li>Server logs: rotated automatically by size.</li>
</ul>

<h2>Your rights</h2>
<p>You can see your data in the service, download your recordings from your lab, and delete your account at any time
on the <a href="/account">Account</a> page. Deleting your account deletes the workspaces only you own, with
everything in them, and removes you from shared ones. You can also ask us to access, correct, export or delete your
data by writing to <a href="mailto:{CONTACT}">{CONTACT}</a>. If you are in the EU or UK, you may complain to your
data protection authority.</p>

<h2>Changes</h2>
<p>If this page changes, we will update the date at the top. For significant changes during the beta, we will tell
beta users before they take effect.</p>
"""
