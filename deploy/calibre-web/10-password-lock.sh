#!/bin/bash
# Passwords are managed at books.sullyflix.com (shelfmark-requests), which keeps
# them in sync across the requests site, Calibre-Web and Audiobookshelf.
# Calibre-Web's "Forgot Password?" would email a random new password and break
# that sync, so on every container start:
#   - the button becomes a link to the requests site's reset page
#   - the login handler ignores forgot=forgot posts
# Admins still set users' passwords from Calibre-Web's admin pages.
# Source of truth: shelfmark-requests repo, deploy/calibre-web/10-password-lock.sh

TEMPLATE=/app/calibre-web/cps/templates/login.html
WEB=/app/calibre-web/cps/web.py
RESET_URL="https://books.sullyflix.com/reset-password"

sed -i "s#<button type=\"submit\" name=\"forgot\" value=\"forgot\" class=\"btn btn-default\">\({{_('Forgot Password?')}}\)</button>#<a class=\"btn btn-default\" href=\"${RESET_URL}\">\1</a>#" "$TEMPLATE"
sed -i "s/if form.get('forgot', \"\") == 'forgot':/if False and form.get('forgot', \"\") == 'forgot':/" "$WEB"

if grep -q "$RESET_URL" "$TEMPLATE" && grep -q "if False and form.get('forgot'" "$WEB"; then
    echo "**** password-lock: Calibre-Web forgot-password routed to $RESET_URL ****"
else
    echo "**** password-lock: WARNING could not patch Calibre-Web (upstream changed?) ****"
fi
