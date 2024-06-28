function getPage() {

    const path = window.location.pathname;

    const pathArray = path.split('/');

    let page = pathArray[1];

    if (page === '') {
        page = 'agenda';
    }

    return page;
}


function highlightNavLink() {

    const mainNav = document.querySelector('#nav-main');
    const navLinks = mainNav.querySelectorAll('.nav-link');

    let link;
    for (link of navLinks) {

        if (link.id === 'nav-' + getPage()) {

            link.classList.add('active');

        }

    }

}


highlightNavLink();
