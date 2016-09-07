/* global django, CKEDITOR */
(function($) {

    /* Improve spacing */
    var style = document.createElement('style');
    style.type = 'text/css';
    style.innerHTML = "div[id*='cke_id_'] {margin-left:170px;}";
    $('head').append(style);

    // Activate and deactivate the CKEDITOR because it does not
    // like getting dragged or its underlying ID changed

    CKEDITOR.config.width = '787';
    CKEDITOR.config.height= '300';
    CKEDITOR.config.format_tags = 'p;h1;h2;h3;h4;pre';
    CKEDITOR.config.toolbar = [[
        'Maximize','-',
        'Format','-',
        'Bold','Italic','Underline','Strike','-',
        'Subscript','Superscript','-',
        'NumberedList','BulletedList','-',
        'Anchor','Link','Unlink','-',
        'Source'
    ]];

    $(document).on(
        'content-editor:activate',
        function(event, $row, formsetName) {
            $row.find('textarea.richtext').each(function() {
                CKEDITOR.replace(this.id, CKEDITOR.config);
            });
        }
    ).on(
        'content-editor:deactivate',
        function(event, $row, formsetName) {
            $row.find('textarea.richtext').each(function() {
                CKEDITOR.instances[this.id] &&
                CKEDITOR.instances[this.id].destroy();
            });
        }
    );
})(django.jQuery);